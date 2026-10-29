"""Plugin extension points around running a browser (any content fetcher).

The lifecycle, in order:

  1. Editing a browser (/browsers/add, /browsers/edit)
       hook browser_config_form_section(base_fetcher, capabilities) -> BrowserConfigSection
       A plugin adds its own WTForms form (and optionally its own template) to a tab of the
       browser's edit page. What the user saves is stored with that browser, in browsers.json, as
       browser_config.plugin_settings[<plugin_id>] - so every watch and group using that browser
       gets it.

  2. Just before the browser is called (a check, or a live Browser Steps session)
       hook browser_request_alter(request, watch, datastore)
       `request` is a BrowserRequest: the url, which engine, the resolved browser config (including
       each plugin's saved settings), headers, cookies, proxy, method and body. Change it in place.
       A plugin that already has the page (e.g. a challenge solver that fetched it) sets
       request.response = BrowserResponse(...) and the browser isn't run at all; the usual
       empty-page and status-code rules still apply to it. (Checks only - a live Browser Steps
       session always needs its browser.)
       May be `async def`. Raising stops the fetch, and the message becomes the watch's error.

  3. After the browser has run (even when it failed), and when a live session is cleaned up
       hook browser_request_finished(request, fetcher, error, watch, datastore)
       For cleanup. `request.fetcher_name` says which engine ran; `request.extra` carries anything
       the plugin stored there in step 2. May be `async def`. Exceptions are logged, never raised.

Plugins import these types from changedetectionio.plugin_api.

Rules for plugins (these matter most on shared / hosted installs, where the people editing browsers
aren't the people running the server):
  - Never take a URL, host, port, path or command from the browser form. Endpoints (a solver, an
    API) come from the operator - environment variables or global settings - otherwise users can
    point them at internal services (SSRF). The same goes for request.proxy_url: only set it from
    operator-controlled values, a user-chosen proxy bypasses the install's egress controls.
  - Exception messages from browser_request_alter() become the watch's visible error: never put
    endpoints, credentials or proxy URLs in them (changedetectionio.proxy_url.redact_proxy_url()).
  - Do network work in `async def` hooks: those are cut off after PLUGIN_ASYNC_HOOK_TIMEOUT, a
    blocking call in a plain hook stalls the worker's event loop with no time limit.
  - Live Browser Steps sessions (request.purpose == 'browser_steps') are started by users at will;
    rate-limit or skip expensive work there.
  - What a section saves must be plain JSON values and at most PLUGIN_SETTINGS_MAX_BYTES; store
    secrets elsewhere (browsers.json is plain text and included in backups).
"""
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from loguru import logger

PLUGIN_ID_PATTERN = re.compile(r'^[a-z0-9][a-z0-9_]{0,63}$')

# Largest a plugin's saved settings may be, as JSON. A plugin form with a free-text field must not
# be able to fill browsers.json (read on every check) with megabytes of user input.
PLUGIN_SETTINGS_MAX_BYTES = 16 * 1024

# Tabs of the browser edit page a section can be added to; anything else becomes its own tab
BROWSER_FORM_TABS = ('browser', 'language', 'request')


@dataclass
class BrowserConfigSection:
    """A plugin's part of the browser edit page.

    plugin_id:   lowercase letters, digits and underscores; also the key its settings are stored under
    label:       heading of the section (and the tab name, when `tab` is a tab of its own)
    form_class:  a wtforms.Form subclass; its validators run when the browser is saved
    tab:         'browser', 'language', 'request', or any other key for a tab of its own
    template:    optional Jinja2 template name (from the plugin's templates/ directory) rendered
                 instead of the default field list; it gets `section` and `subform`
    description: optional text shown under the heading
    """
    plugin_id: str
    label: Any
    form_class: Any
    tab: str = 'browser'
    template: Optional[str] = None
    description: Any = None

    @property
    def field_name(self):
        """Name of this section's FormField on the browser form (and its HTML input prefix)."""
        return f"plugin_{self.plugin_id}"

    @property
    def has_own_tab(self):
        return self.tab not in BROWSER_FORM_TABS


@dataclass
class BrowserResponse:
    """A page a plugin already has. Set as request.response in browser_request_alter() to use it
    instead of running the browser."""
    content: str
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class BrowserRequest:
    """Everything about to be handed to the browser. browser_request_alter() hooks change it in place."""
    url: str
    fetcher_name: str                       # engine, e.g. 'html_webdriver', 'html_requests'
    fetcher_class: Any                      # the content fetcher class that will run
    browser_config: Any                     # resolved FetcherConfig of the browser the watch uses
    headers: Any                            # requests.structures.CaseInsensitiveDict
    cookies: List[Dict[str, Any]] = field(default_factory=list)  # Playwright-style cookie dicts
    proxy_url: Optional[str] = None
    method: Optional[str] = None
    body: Optional[str] = None
    watch_uuid: Optional[str] = None
    purpose: str = 'check'                  # 'check' or 'browser_steps' (a live session)
    extra: Dict[str, Any] = field(default_factory=dict)  # plugin state from alter to finished
    response: Optional[BrowserResponse] = None  # set by a plugin to skip the browser (checks only)

    def plugin_settings(self, plugin_id):
        """This browser's saved settings for `plugin_id` (a copy), {} when it has none."""
        if self.browser_config is None:
            return {}
        return self.browser_config.plugin_config(plugin_id)

    def cookies_for_browser(self):
        """The cookies with a scope every engine accepts: a cookie with neither `url` nor `domain`
        is scoped to the requested URL, so it is never sent to other sites."""
        out = []
        for cookie in self.cookies or []:
            if not isinstance(cookie, dict) or not cookie.get('name'):
                logger.warning(f"Ignoring a cookie without a name: {cookie!r}")
                continue
            cookie = dict(cookie)
            cookie.setdefault('value', '')
            if cookie.get('domain'):
                # Engines take either a url or a domain (+ path), never both
                cookie.pop('url', None)
                cookie.setdefault('path', '/')
            elif not cookie.get('url'):
                cookie['url'] = self.url
            out.append(cookie)
        return out


def get_browser_config_sections(base_fetcher, capabilities):
    """Every plugin section for editing a browser built on `base_fetcher`, in registration order,
    with invalid ones logged and dropped."""
    from changedetectionio.pluggy_interface import plugin_manager
    from wtforms import Form

    sections = []
    seen = set()
    results = plugin_manager.hook.browser_config_form_section(base_fetcher=base_fetcher,
                                                              capabilities=capabilities)
    for section in reversed(results):
        if section is None:
            continue
        if not isinstance(section, BrowserConfigSection):
            logger.error(f"browser_config_form_section must return a BrowserConfigSection, got {type(section).__name__}")
            continue
        if not PLUGIN_ID_PATTERN.match(section.plugin_id or ''):
            logger.error(f"Invalid plugin_id {section.plugin_id!r} for a browser config section")
            continue
        if not (isinstance(section.form_class, type) and issubclass(section.form_class, Form)):
            logger.error(f"Browser config section '{section.plugin_id}' form_class must be a wtforms.Form subclass")
            continue
        if section.plugin_id in seen:
            logger.error(f"Two browser config sections use plugin_id '{section.plugin_id}', ignoring the second")
            continue
        seen.add(section.plugin_id)
        sections.append(section)
    return sections


def section_settings_error(data):
    """Why a section's submitted settings can't be stored, or None when they can.

    They are saved to browsers.json, so they must be plain JSON values (a DecimalField or DateField
    would make the save itself fail) and stay small."""
    import json
    try:
        encoded = json.dumps(data)
    except (TypeError, ValueError):
        return "Plugin settings must be plain text, numbers, true/false or lists of those"
    if len(encoded.encode('utf-8')) > PLUGIN_SETTINGS_MAX_BYTES:
        return f"Plugin settings are larger than {PLUGIN_SETTINGS_MAX_BYTES // 1024} KB"
    return None


def form_class_with_sections(base_form_class, sections):
    """`base_form_class` with each section's form attached as a FormField. WTForms only binds
    fields when a class is created, so this builds a subclass rather than adding fields later."""
    if not sections:
        return base_form_class
    from wtforms import FormField
    attrs = {section.field_name: FormField(section.form_class, label=section.label) for section in sections}
    return type(f"{base_form_class.__name__}WithPlugins", (base_form_class,), attrs)


def _request_snapshot(request):
    return {
        'headers': {k.lower(): v for k, v in dict(request.headers or {}).items()},
        'cookies': [c.get('name') for c in (request.cookies or []) if isinstance(c, dict)],
        'proxy_url': request.proxy_url,
        'method': request.method,
        'body': request.body,
    }


def describe_request_changes(before, request):
    """What the plugins changed, for the log - header names (and the User-Agent value), cookie
    names, never cookie values or other header values, which can be credentials."""
    from changedetectionio.proxy_url import redact_proxy_url
    after = _request_snapshot(request)
    changes = []
    changed_headers = sorted(k for k in set(before['headers']) | set(after['headers'])
                             if before['headers'].get(k) != after['headers'].get(k))
    if changed_headers:
        names = [f"user-agent='{after['headers'].get('user-agent')}'" if k == 'user-agent' else k
                 for k in changed_headers]
        changes.append(f"headers [{', '.join(names)}]")
    added_cookies = after['cookies'][len(before['cookies']):] if after['cookies'][:len(before['cookies'])] == before['cookies'] \
        else after['cookies']
    if added_cookies:
        changes.append(f"{len(added_cookies)} cookie(s) [{', '.join(str(n) for n in added_cookies)}]")
    if after['proxy_url'] != before['proxy_url']:
        changes.append(f"proxy '{redact_proxy_url(before['proxy_url'])}' -> '{redact_proxy_url(after['proxy_url'])}'")
    if after['method'] != before['method']:
        changes.append(f"method {before['method']} -> {after['method']}")
    if after['body'] != before['body']:
        changes.append("body")
    if request.response is not None:
        changes.append(f"supplied the page themselves (status {request.response.status_code}), the browser won't run")
    return changes


async def apply_browser_request_alter(request, watch, datastore):
    """Run every browser_request_alter() on `request`, awaiting async ones, in hook order, and log
    what they changed."""
    from changedetectionio.pluggy_interface import plugin_manager
    from changedetectionio.plugin_api import gather_hook_results
    before = _request_snapshot(request)
    results = plugin_manager.hook.browser_request_alter(request=request, watch=watch, datastore=datastore)
    await gather_hook_results(results)
    changes = describe_request_changes(before, request)
    if changes:
        logger.info(f"Watch {request.watch_uuid} ({request.purpose}, '{request.fetcher_name}'): plugins changed "
                    f"the request: {'; '.join(changes)}")
    return request


async def apply_browser_request_finished(request, fetcher, error, watch, datastore):
    """Run every browser_request_finished(). Never raises."""
    from changedetectionio.pluggy_interface import plugin_manager
    from changedetectionio.plugin_api import gather_hook_results
    try:
        results = plugin_manager.hook.browser_request_finished(request=request, fetcher=fetcher, error=error,
                                                               watch=watch, datastore=datastore)
        await gather_hook_results(results)
    except Exception as e:
        logger.error(f"browser_request_finished hook failed: {e}")
