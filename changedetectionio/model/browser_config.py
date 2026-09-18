"""
Browser configs ("browser profiles") - named, engine-agnostic browser behaviour that a
watch can select (viewport / locale / timezone / asset-blocking ...).

Two layers live here:

  * FetcherConfig      - the behaviour schema. A watch resolves one of these (watch -> group
                         -> system default) and it is injected onto the content fetcher as
                         `.browser_config`; an updated fetcher applies the fields it can
                         honour and ignores the rest (capability-gated, e.g. block_* needs
                         FetcherCapabilities.supports_request_blocking). It is ALSO the on-disk
                         schema for each browsers.json entry.

  * BrowserConfigStore - persistence manager for browsers.json, mirroring proxies.json: an
                         optional file loaded lazily, with CRUD + a single default. Absent
                         file == no user configs == built-in default behaviour, so there is
                         nothing to create at startup.

browsers.json shape:
    { "<stable-id>": {"label": str, "base_fetcher": str, "is_default": bool,
                      "browser_config": { <FetcherConfig fields> }}, ... }

The id is a stable uuid assigned once (NOT a hash of the settings) so editing a config never
orphans the watches that reference it.
"""
import os
import uuid as uuid_builder
from os import path
from typing import ClassVar, Dict, List, Optional

from loguru import logger
from pydantic import BaseModel, Field, ValidationError, field_validator

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json
    HAS_ORJSON = False


# Default plain-HTTP-client request timeout (seconds). Fixed, NOT read from the environment at
# call time: the old settings.requests.timeout was baked once at startup, and resolving it lazily
# per-fetch made tests (which set DEFAULT_SETTINGS_REQUESTS_TIMEOUT low) time out on slow endpoints.
# A user who wants a different value sets it per-browser on the /browsers tab; upgrades preserve the
# old global value via update_35.
DEFAULT_REQUEST_TIMEOUT_SECONDS = 45


class BrowserConfigDoesntExist(Exception):
    """A watch/group references a browser config id that no longer exists in browsers.json."""
    def __init__(self, config_id, uuid=None):
        self.config_id = config_id
        self.uuid = uuid
        super().__init__(
            f"Browser config '{config_id}' no longer exists"
            f"{f' (watch {uuid})' if uuid else ''} - edit the watch/group and choose a browser."
        )


def _available_timezones():
    # Cached IANA tz set (zoneinfo builds it fresh each call, ~1ms).
    global _TZ_CACHE
    try:
        return _TZ_CACHE
    except NameError:
        from zoneinfo import available_timezones
        _TZ_CACHE = available_timezones()
        return _TZ_CACHE


def _needs(capability, required=False, **field_kwargs):
    """A FetcherConfig field only the engines with `capability` may carry.

    The capability rides on the field itself rather than in a separate name->flag table, so
    there is exactly one place to declare a field and no second list to keep in step. Read back
    by FetcherConfig.applicable_fields(), which drives BOTH which fields the /browsers form
    renders and which ones may be saved.

    `required=True` means an engine that has this capability cannot work without a value (an
    external browser with no endpoint has nothing to connect to), enforced on submitted input by
    required_fields(). The field itself stays Optional because the model is shared by every
    engine, most of which must not carry it at all.
    """
    if 'default_factory' not in field_kwargs:
        field_kwargs.setdefault('default', None)
    return Field(json_schema_extra={'capability': capability, 'required_when_applicable': required},
                 **field_kwargs)


class FetcherConfig(BaseModel):
    """Engine-agnostic per-instance browser behaviour.

    Unlike LLMSettings we deliberately do NOT use extra='forbid': this is a schema that gets
    written to disk (browsers.json) and backed up/restored across app versions, so it must
    tolerate version skew (a key removed in a future release should still load). There are no
    privileged fields here to protect against mass-assignment - everything is user-settable.
    Keep every field optional with a sensible default.
    """
    # Rendering / device
    viewport_width: Optional[int] = _needs('supports_screenshots')   # px; None -> engine default
    viewport_height: Optional[int] = _needs('supports_screenshots')
    # Identity / locale
    locale: Optional[str] = _needs('supports_screenshots')           # e.g. 'de-DE' -> Accept-Language + navigator.language
    timezone_id: Optional[str] = _needs('supports_screenshots')      # e.g. 'Europe/Berlin'
    # Screenshot
    screenshot_format: str = _needs('supports_screenshots', default='JPEG')
    # Cost / bandwidth - block assets (capability-gated by supports_request_blocking)
    block_resource_types: List[str] = _needs('supports_request_blocking', default_factory=list)  # e.g. ['image', 'font', 'media']
    block_url_patterns: List[str] = _needs('supports_request_blocking', default_factory=list)    # globs, e.g. ['*.ttf', '*/analytics/*']
    # Local-launch engines only (capability-gated by supports_browser_type)
    browser_type: Optional[str] = _needs('supports_browser_type')    # 'chromium' | 'firefox' | 'webkit'
    # Delete the per-fetch temp profile after use (capability-gated by supports_delete_created_files)
    delete_created_files: bool = _needs('supports_delete_created_files', default=True)
    # timeout: plain HTTP client only (capability-gated by supports_request_timeout).
    # Defaults to DEFAULT_REQUEST_TIMEOUT_SECONDS (45s) so a fresh install / built-in html_requests
    # config has a sane, browser-like read timeout without relying on any global setting. An
    # existing install's previous settings.requests.timeout is carried onto its html_requests
    # config by update_35 (the migration hook), so upgrades keep whatever the user had.
    timeout: Optional[int] = _needs('supports_request_timeout', default=DEFAULT_REQUEST_TIMEOUT_SECONDS)   # request timeout in seconds
    # connection_url: the endpoint of an external browser this profile talks to (capability
    # supports_connection_url). CDP over a WebSocket, e.g. a Bright Data / Oxylabs Scraping
    # Browser or a second sockpuppetbrowser. Commonly carries credentials, so never log it.
    connection_url: Optional[str] = _needs('supports_connection_url', required=True)
    # user_agent: honoured by every engine (capability supports_custom_user_agent) via the
    # request_headers User-Agent channel.
    user_agent: Optional[str] = _needs('supports_custom_user_agent') # overrides the User-Agent header for this profile

    @classmethod
    def applicable_fields(cls, capabilities):
        """The field names an engine with these `capabilities` may carry.

        `capabilities` is a FetcherCapabilities or its .model_dump() dict (the blueprint holds
        one of each). A field declared without _needs() applies to every engine; an unknown/None
        capability set yields only those, so a made-up base engine can never widen what is
        storable.
        """
        def _has(flag):
            if capabilities is None:
                return False
            if isinstance(capabilities, dict):
                return bool(capabilities.get(flag))
            return bool(getattr(capabilities, flag, False))

        return {name for name, extra in cls._field_metadata().items()
                if extra.get('capability') is None or _has(extra['capability'])}

    @classmethod
    def _field_metadata(cls):
        """{field_name: its _needs() metadata dict} - {} for fields declared without it."""
        return {name: (field.json_schema_extra if isinstance(field.json_schema_extra, dict) else {})
                for name, field in cls.model_fields.items()}

    @classmethod
    def required_fields(cls, capabilities):
        """Applicable fields an engine with these capabilities cannot work without."""
        applicable = cls.applicable_fields(capabilities)
        return {name for name, extra in cls._field_metadata().items()
                if name in applicable and extra.get('required_when_applicable')}

    @classmethod
    def from_submitted(cls, data, capabilities):
        """Build from untrusted input (a form POST), dropping every field this engine cannot
        honour. The engine's capabilities are the allowlist, so a crafted POST - or an
        unrendered field falling back to its own widget default - cannot put a setting on a
        browser that ignores it.

        Deliberately NOT used when loading browsers.json: reads stay tolerant so a file written
        by another version still parses (see the module docstring).
        """
        allowed = cls.applicable_fields(capabilities)
        return cls(**{k: v for k, v in (data or {}).items() if k in allowed})

    @field_validator('timeout')
    @classmethod
    def _validate_timeout(cls, v):
        if v is not None and not (1 <= v <= 999):
            raise ValueError("Timeout must be between 1 and 999 seconds")
        return v

    def apply_user_agent(self, request_headers):
        """Set this profile's User-Agent on request_headers (the channel every fetcher - plain
        client and browsers - uses), if configured. Applied early (before a watch's own headers)
        so an explicit per-watch User-Agent still wins. Works for dict / CaseInsensitiveDict.
        A None user_agent is a no-op. Returns request_headers for chaining."""
        if self.user_agent:
            for k in [k for k in list(request_headers.keys()) if k.lower() == 'user-agent']:
                del request_headers[k]
            request_headers['User-Agent'] = self.user_agent
        return request_headers

    def browser_context_kwargs(self):
        """The per-profile browser-context options this config implies (viewport / locale /
        timezone). Unset fields are omitted so engine defaults are preserved. Single source of
        truth so every caller (the real fetch, the Browser Steps live UI, the Add-Watch preview)
        just does `context_kwargs.update(cfg.browser_context_kwargs())` instead of repeating field
        names. The key/value shape follows the CDP/Playwright `new_context()` dialect, which the
        browser engines that honour these fields (Playwright, CloakBrowser, playwright_builtin) use."""
        kwargs = {}
        if self.locale:
            kwargs['locale'] = self.locale
        if self.timezone_id:
            kwargs['timezone_id'] = self.timezone_id
        if self.viewport_width and self.viewport_height:
            kwargs['viewport'] = {'width': self.viewport_width, 'height': self.viewport_height}
        return kwargs

    def effective_timeout(self, default):
        """This profile's request timeout, else the caller's default (plain HTTP client only)."""
        return self.timeout or default

    @field_validator('connection_url')
    @classmethod
    def _validate_connection_url(cls, v):
        # The engine connects to whatever this says, so the scheme is enforced at the model (not
        # just in the form): CDP over a WebSocket is the only thing html_external_cdp speaks, and
        # a wrong scheme here used to be accepted and then silently handed to a WebDriver client.
        # Control characters are refused for the same reason as user_agent.
        if not v:
            return v
        v = v.strip()
        if any(ord(c) < 0x20 or ord(c) == 0x7f for c in v):
            raise ValueError("Browser connection URL cannot contain control characters")
        if not v.lower().startswith(('ws://', 'wss://')):
            raise ValueError("Browser connection URL must start with ws:// or wss://")
        return v

    @field_validator('user_agent')
    @classmethod
    def _validate_user_agent(cls, v):
        # This value is written straight into an outbound request header (apply_user_agent), so
        # CR/LF or other control characters have no legitimate use here and are exactly what a
        # header-splitting attempt looks like. The HTTP clients would reject them anyway; refusing
        # at the model means it can never be persisted in browsers.json in the first place.
        if v and any(ord(c) < 0x20 or ord(c) == 0x7f for c in v):
            raise ValueError("User-Agent cannot contain control characters")
        return v

    @field_validator('browser_type')
    @classmethod
    def _validate_browser_type(cls, v):
        if v and v not in ('chromium', 'firefox', 'webkit'):
            raise ValueError(f"Unknown browser_type '{v}' - use chromium, firefox or webkit")
        return v

    @field_validator('locale')
    @classmethod
    def _validate_locale(cls, v):
        """BCP-47 tag validated against babel's CLDR data (e.g. 'de-DE', 'en-GB')."""
        if not v:
            return v
        from babel import Locale, UnknownLocaleError
        try:
            Locale.parse(v.strip(), sep='-')
        except (UnknownLocaleError, ValueError):
            raise ValueError(f"Unknown locale '{v}' - use a BCP-47 tag like 'de-DE' or 'en-GB'")
        return v.strip()

    @field_validator('timezone_id')
    @classmethod
    def _validate_timezone(cls, v):
        """IANA timezone name validated against the stdlib zoneinfo database."""
        if not v:
            return v
        if v.strip() not in _available_timezones():
            raise ValueError(f"Unknown IANA timezone '{v}' - e.g. 'Europe/Berlin', 'UTC'")
        return v.strip()


class BrowserConfigEntry(BaseModel):
    """One browsers.json entry (the id is the dict key, not stored in the entry).

    Note: there is deliberately no `is_default` here. The default browser is the global
    settings.application.fetch_backend (a single source of truth that can point at a built-in
    engine OR a browser-config id), so it doesn't live per-entry - see
    ChangeDetectionStore.get_default_backend() / Watch.get_fetch_backend.
    """
    label: str = ''
    base_fetcher: str = 'html_webdriver'
    browser_config: FetcherConfig = Field(default_factory=FetcherConfig)


class BrowserConfigStore:
    """Persistence manager for browsers.json. Thin, self-contained, backup-friendly."""

    def __init__(self, datastore_path, lock):
        self._path = os.path.join(datastore_path, 'browsers.json')
        self._lock = lock
        # mtime-keyed cache of the parsed file. all()/get() are hit per-watch on every watchlist
        # render + fetch resolution, so re-reading + re-parsing browsers.json each time is real
        # amplification (cf. the favicon-glob fix). Cache the parsed dict and only re-read when
        # the file's mtime changes - picks up edits (save bumps mtime) without staleness.
        self._cache = None
        self._cache_mtime = None

    # ---- low level load/save ----
    def all(self):
        """Validated dict {id: entry-dict}. Empty dict when the file is absent. mtime-cached.

        This is the single read-side validation gate: browsers.json can be hand-edited, restored
        from an older/newer version, or corrupted, so every entry is coerced through
        BrowserConfigEntry here rather than trusted raw. A malformed entry is dropped (with a
        warning) instead of crashing every consumer downstream - callers get clean, normalized
        dicts with the expected shape. Unknown extra keys inside browser_config are still tolerated
        (FetcherConfig has no extra='forbid') for cross-version compatibility.
        """
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            # File absent (or unreadable) - nothing configured yet.
            self._cache, self._cache_mtime = {}, None
            return {}
        if self._cache is not None and self._cache_mtime == mtime:
            return self._cache
        try:
            if HAS_ORJSON:
                with open(self._path, 'rb') as f:
                    data = orjson.loads(f.read()) or {}
            else:
                with open(self._path, encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception as e:
            logger.error(f"Could not load browsers.json: {e}")
            return {}
        # Top level must be an id->entry mapping; anything else (a list, a scalar) is corrupt.
        if not isinstance(data, dict):
            logger.error(f"browsers.json is not a JSON object (got {type(data).__name__}) - ignoring")
            self._cache, self._cache_mtime = {}, mtime
            return {}
        clean = {}
        for cid, raw in data.items():
            try:
                clean[cid] = BrowserConfigEntry(**raw).model_dump()
            except (ValidationError, TypeError) as e:
                logger.warning(f"Dropping malformed browsers.json entry '{cid}': {e}")
        self._cache, self._cache_mtime = clean, mtime
        return clean

    def _save(self, configs):
        # Deferred import avoids a model -> store import cycle at module load.
        from changedetectionio.store.file_saving_datastore import save_json_atomic
        with self._lock:
            save_json_atomic(self._path, configs, label="browsers")
        # Invalidate so the next all()/get() re-reads (its mtime will differ anyway).
        self._cache, self._cache_mtime = None, None

    # ---- CRUD ----
    def get(self, config_id):
        return self.all().get(config_id)

    def add(self, label, base_fetcher, browser_config=None):
        """Create a config; returns its stable id."""
        configs = self.all()
        new_id = str(uuid_builder.uuid4())
        configs[new_id] = BrowserConfigEntry(
            label=label,
            base_fetcher=base_fetcher,
            browser_config=FetcherConfig(**(browser_config or {})),
        ).model_dump()
        self._save(configs)
        return new_id

    def upsert(self, config_id, label, base_fetcher, browser_config=None):
        """Create-or-replace an entry at a specific key. Used for built-in engine configs,
        which are keyed by the engine name (e.g. 'html_webdriver') rather than a uuid."""
        configs = self.all()
        configs[config_id] = BrowserConfigEntry(
            label=label,
            base_fetcher=base_fetcher,
            browser_config=FetcherConfig(**(browser_config or {})),
        ).model_dump()
        self._save(configs)
        return config_id

    def update(self, config_id, label=None, base_fetcher=None, browser_config=None):
        configs = self.all()
        raw = configs.get(config_id)
        if not raw:
            return False
        entry = BrowserConfigEntry(**raw)
        if label is not None:
            entry.label = label
        if base_fetcher is not None:
            entry.base_fetcher = base_fetcher
        if browser_config is not None:
            entry.browser_config = FetcherConfig(**browser_config)
        configs[config_id] = entry.model_dump()
        self._save(configs)
        return True

    def delete(self, config_id):
        configs = self.all()
        if config_id in configs:
            del configs[config_id]
            self._save(configs)
            return True
        return False

    def resolve_config(self, config_id):
        """Validated FetcherConfig for an id, or None if the id is unknown."""
        raw = self.get(config_id)
        if not raw:
            return None
        return FetcherConfig(**(raw.get('browser_config') or {}))

    def engine_and_config(self, selected):
        """Map an already-resolved selector to (entry, engine_name, FetcherConfig).

        The single place the trio of resolvers (content fetcher, watchlist status icon,
        capability checks) turns a selector into its engine + behaviour:
          - a stored browser config -> (entry, its base_fetcher, its FetcherConfig)
          - a built-in engine name  -> (None, that name, empty FetcherConfig)
        `entry is None` also tells the caller the selector wasn't a saved config (so it can do
        the built-in / extra_browser / dangling-id handling).
        """
        entry = self.get(selected) if selected else None
        if entry:
            return entry, (entry.get('base_fetcher') or 'html_webdriver'), FetcherConfig(**(entry.get('browser_config') or {}))
        return None, selected, FetcherConfig()


# One BrowserConfigStore instance per datastore path, so the mtime cache is shared by everything
# reading browsers.json (the ChangeDetectionStore and every Watch, which only holds the data dict
# + its path). The ChangeDetectionStore registers its own (lock-bearing) instance here so writes
# and the watch-side reads go through the same cache.
_STORE_REGISTRY = {}


def register_browser_config_store(datastore_path, store):
    _STORE_REGISTRY[datastore_path] = store


def get_browser_config_store(datastore_path):
    """The shared BrowserConfigStore for a datastore path (created read-only if none registered)."""
    store = _STORE_REGISTRY.get(datastore_path)
    if store is None:
        store = BrowserConfigStore(datastore_path, lock=None)
        _STORE_REGISTRY[datastore_path] = store
    return store


def list_builtin_browsers():
    """Built-in engine 'browsers' - always present, zero-override config.

    These are the engines the app instantiated at boot (available_fetchers() already reflects
    the env-driven html_webdriver -> playwright/puppeteer/selenium choice), exposed as
    selectable browsers with a stable id == the engine name. That id equals the value existing
    watches already store in fetch_backend, so nothing breaks and they always show in the list.
    """
    from changedetectionio import content_fetchers
    out = []
    for name, description in content_fetchers.available_fetchers():
        cls = getattr(content_fetchers, name, None)
        # Skip "base only" engines (e.g. html_playwright_builtin) - they aren't usable directly,
        # only as the base of a browser config (chosen in the Add Browser form).
        if cls is not None and not getattr(cls, 'ready_to_use', True):
            continue
        out.append({'id': name, 'label': description, 'base_fetcher': name})
    return out


def is_valid_browser_selector(value, datastore, allow_empty=True):
    """True when `value` is something a watch may legitimately store in fetch_backend.

    That is: 'system' (follow the global default), an installed engine name (built-in or
    plugin-provided), or the id of a saved browser config - which is what a migrated
    'extra_browser_<name>' endpoint is since update_36.

    THE one answer to this question. The API (create/update/import), the quick-add form
    validator and the bulk "set browser" operation each used to keep their own copy, which is how
    they ended up disagreeing about whether a browser-config id was acceptable.
    """
    from changedetectionio import content_fetchers

    if not value:
        return allow_empty
    if value == 'system':
        return True
    store = getattr(datastore, 'browser_config_store', None) if datastore is not None else None
    if store is not None and store.get(value):
        return True
    return value in {name for name, _description in content_fetchers.available_fetchers()}


def list_watch_browser_choices(datastore):
    """(value, label) choices for the watch-level 'Browser' picker:
    system default, the always-present built-in engine browsers, then the user's saved browsers.

    Deduplicated by value, because a saved config legitimately shares a built-in engine's id -
    update_35 migrated the old per-engine request timeout / User-Agent into configs keyed
    'html_requests' and 'html_webdriver' - and listing one browser twice is not a choice. The
    saved label wins: it is the same browser, and that is the name the user can change.
    """
    choices = {'system': _system_default_label(datastore)}
    for b in list_builtin_browsers():
        choices[b['id']] = b['label']
    for cid, entry in datastore.browser_config_store.all().items():
        choices[cid] = entry.get('label') or cid
    # dict keeps each value's first position (built-ins stay in engine order) with its last label
    return list(choices.items())


def _system_default_label(datastore):
    from flask_babel import gettext
    return gettext('Default (system settings)')


# "Which of these can drive the LIVE interactive browser (screenshots + visual selector)?" is
# deliberately NOT answered here - it lives in blueprint/add_watch_ui/browser_config.py, which
# filters list_watch_browser_choices() above through one capability check. Keeping it in a single
# place is what stops the Add-Watch page, its /snapshot endpoint and the sidebar gate from
# disagreeing about which browsers are usable.


# --- Thin free-function delegators --------------------------------------------------------
# The resolution chain (PDF / group override / watch / 'system' -> global default) lives on the
# Watch model now (Watch.get_fetch_backend & friends) - only watches fetch, so the watch owns
# "what do I fetch with?". These wrappers keep the historical (watch, datastore) call shape for
# templates/blueprints/tests; `datastore` is accepted but unused (the Watch self-resolves).

def resolve_watch_fetcher_engine(watch, datastore=None):
    """The concrete engine name that will actually fetch this watch. See Watch.resolved_fetch_engine."""
    return watch.resolved_fetch_engine


def resolve_browser_config_override(watch, datastore=None):
    """If a group/tag overrides this watch's browser config, describe it, else None.
    See Watch.browser_config_override."""
    return watch.browser_config_override


def resolve_watch_browser_display(watch, datastore=None):
    """Display info for the watchlist status icon: which browser a watch effectively uses.

    Returns dict: {engine, browser_type, label, is_named, group_title} where `label` is the
    named browser-config's label (or the built-in engine description), `browser_type` is the
    resolved sub-engine (firefox/chromium/webkit) if set, and `group_title` is set when a group
    override supplies it.
    """
    from changedetectionio import content_fetchers
    store = watch.browser_config_store
    override = watch.browser_config_override

    entry, engine, cfg = store.engine_and_config(watch.get_fetch_backend)
    if entry:
        label = entry.get('label')
    else:
        label = dict(content_fetchers.available_fetchers()).get(engine, engine)

    return {
        'engine': engine,
        'browser_type': cfg.browser_type,
        'label': label,
        'is_named': entry is not None,
        'group_title': override['group_title'] if override else None,
    }
