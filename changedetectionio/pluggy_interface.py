import pluggy
import os
import importlib
import inspect
import sys
import threading
import time
from functools import wraps
from loguru import logger

# Global plugin namespace for changedetection.io
PLUGIN_NAMESPACE = "changedetectionio"

# Conditions plugins used to have their own PluginManager under this name. Their hooks now live on
# the main manager, but implementations marked with the old namespace are still picked up (see
# ChangeDetectionPluginManager.parse_hookimpl_opts) and the old entry-point group is still loaded.
LEGACY_CONDITIONS_NAMESPACE = "changedetectionio_conditions"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
# The public marker, see plugin_api for why it's defined there
from changedetectionio.plugin_api import hookimpl  # noqa: E402

# A plugin that raises is logged and counted, and the hook carries on with the other plugins.
# After this many failures in a row the plugin is reported as "errored" (it is still called).
PLUGIN_CONSECUTIVE_FAILURES_ERRORED = int(os.getenv('PLUGIN_CONSECUTIVE_FAILURES_ERRORED', 5))
# Upper bound for an async hook implementation, so a hung plugin can't stall a check forever.
PLUGIN_ASYNC_HOOK_TIMEOUT = float(os.getenv('PLUGIN_ASYNC_HOOK_TIMEOUT', 120))

# Hooks whose exceptions must reach the caller (after being logged and counted), for example a
# future fetch hook that raises EmptyReply on purpose. Every other hook swallows plugin exceptions.
HOOKS_THAT_PROPAGATE_EXCEPTIONS = {
    # A plugin that can't prepare the request (e.g. a challenge solver failing) must stop the
    # fetch with its message as the watch's error, rather than fetching without what it needed
    'browser_request_alter',
}


class ChangeDetectionSpec:
    """Hook specifications for extending changedetection.io functionality."""

    @hookspec
    def ui_edit_stats_extras(watch):
        """Return HTML content to add to the stats tab in the edit view.

        Args:
            watch: The watch object being edited

        Returns:
            str: HTML content to be inserted in the stats tab
        """
        pass

    @hookspec
    def register_content_fetcher(self):
        """Return a tuple of (fetcher_name, fetcher_class) for content fetcher plugins.

        The fetcher_name should start with 'html_' and the fetcher_class
        should inherit from changedetectionio.content_fetchers.base.Fetcher

        Returns:
            tuple: (str: fetcher_name, class: fetcher_class)
        """
        pass

    @hookspec
    def fetcher_status_icon(fetcher_name):
        """Return status icon HTML attributes for a content fetcher.

        Args:
            fetcher_name: The name of the fetcher (e.g., 'html_webdriver', 'html_js_zyte')

        Returns:
            str: HTML string containing <img> tags or other status icon elements
                 Empty string if no custom status icon is needed
        """
        pass

    @hookspec
    def plugin_static_path(self):
        """Return the path to the plugin's static files directory.

        Returns:
            str: Absolute path to the plugin's static directory, or None if no static files
        """
        pass

    @hookspec(firstresult=True)
    def get_itemprop_availability_override(self, content, fetcher_name, fetcher_instance, url, llm_intent, text):
        """Provide custom implementation of get_itemprop_availability for a specific fetcher.

        This hook allows plugins to provide their own product availability detection
        when their fetcher is being used. This is called as a fallback when the built-in
        method doesn't find good data.

        The first implementation to return a non-None result wins and the rest are skipped,
        so return None (not an empty dict) when you have nothing. The built-in LLM restock
        plugin (litellm) is registered trylast, so your own plugin, for example one that
        POSTs to an LLM with plain `requests`, always gets the first go and the built-in
        one is never billed when yours already answered. See plugins/llm_restock.py for
        the prompt, cache and reply-parsing helpers you can reuse without importing litellm.

        Args:
            content: The HTML content that was just fetched
            fetcher_name: The name of the fetcher being used (e.g., 'html_js_zyte')
            fetcher_instance: The fetcher instance that generated the content
            url: The URL being watched/checked
            llm_intent: Optional user-supplied intent string (e.g. "alert when price drops below $300")
            text: The same content converted with html_to_text(). Only computed when an
                  implementation declares this argument, so leave it out if you don't need it.

        Declare the arguments you want WITHOUT default values (`text`, not `text=None`),
        pluggy silently never passes an argument that has a default.

        Returns:
            dict or None: Dictionary with availability data:
                {
                    'price': float or None,
                    'availability': str or None,  # e.g., 'in stock', 'out of stock'
                    'currency': str or None,      # e.g., 'USD', 'EUR'
                }
                Or None if this plugin doesn't handle this fetcher or couldn't extract data
        """
        pass

    @hookspec
    def plugin_settings_tab(self):
        """Return settings tab information for this plugin.

        This hook allows plugins to add their own settings tab to the settings page.
        Settings will be saved to a separate JSON file in the datastore directory.

        Returns:
            dict or None: Dictionary with settings tab information:
                {
                    'plugin_id': str,           # Unique identifier (e.g., 'zyte_fetcher')
                    'tab_label': str,           # Display name for tab (e.g., 'Zyte Fetcher')
                    'form_class': Form,         # WTForms Form class for the settings
                    'template_path': str,       # Optional: path to Jinja2 template (relative to plugin)
                                                # If not provided, a default form renderer will be used
                }
                Or None if this plugin doesn't provide settings
        """
        pass

    @hookspec
    def register_processor(self):
        """Register an external processor plugin.

        External packages can implement this hook to register custom processors
        that will be discovered alongside built-in processors.

        Returns:
            dict or None: Dictionary with processor information:
                {
                    'processor_name': str,      # Machine name (e.g., 'osint_recon')
                    'processor_module': module, # Module containing processor.py
                    'processor_class': class,   # The perform_site_check class
                    'metadata': {               # Optional metadata
                        'name': str,            # Display name
                        'description': str,     # Description
                        'processor_weight': int,# Sort weight (lower = higher priority)
                        'list_badge_text': str, # Badge text for UI
                    }
                }
                Return None if this plugin doesn't provide a processor
        """
        pass

    @hookspec
    def update_handler_alter(update_handler, watch, datastore):
        """Modify or wrap the update_handler before it processes a watch.

        This hook is called after the update_handler (perform_site_check instance) is created
        but before it calls call_browser() and run_changedetection(). Plugins can use this to:
        - Wrap the handler to add logging/metrics
        - Modify handler configuration
        - Add custom preprocessing logic

        Args:
            update_handler: The perform_site_check instance that will process the watch
            watch: The watch dict being processed
            datastore: The application datastore

        Returns:
            object or None: Return a modified/wrapped handler, or None to keep the original.
                           If multiple plugins return handlers, they are chained in registration order.
        """
        pass

    @hookspec
    def update_finalize(update_handler, watch, datastore, processing_exception):
        """Called after watch processing completes (success or failure).

        This hook is called in the finally block after all processing is complete,
        allowing plugins to perform cleanup, update metrics, or log final status.

        The plugin can access update_handler.last_logging_insert_id if it was stored
        during update_handler_alter, and use processing_exception to determine if
        the processing succeeded or failed.

        Args:
            update_handler: The perform_site_check instance (may be None if creation failed)
            watch: The watch dict that was processed (may be None if not loaded)
            datastore: The application datastore
            processing_exception: The exception from the main processing block, or None if successful.
                                 This does NOT include cleanup exceptions - only exceptions from
                                 the actual watch processing (fetch, diff, etc).

        Returns:
            None: This hook doesn't return a value
        """
        pass

    @hookspec
    def get_html_head_extras():
        """Return HTML to inject into the <head> of every page via base.html.

        Plugins can use this to add <script>, <style>, or <link> tags that should
        be present on all pages.  Return a raw HTML string or None.

        IMPORTANT: Always use Flask's url_for() for any src/href URLs so that
        sub-path deployments (nginx reverse proxy with USE_X_SETTINGS / X-Forwarded-Prefix)
        work correctly.  This hook is called inside a request context so url_for() is
        always available.

        For small amounts of CSS/JS, return them inline — no file-serving needed::

            from changedetectionio.pluggy_interface import hookimpl

            @hookimpl
            def get_html_head_extras(self):
                return (
                    '<style>.my-module-banner { color: red; }</style>\\n'
                    '<script>console.log("my_module_content loaded");</script>'
                )

        For larger assets, register your own lightweight Flask routes in the plugin
        module and point to them with url_for() so the sub-path prefix is handled
        automatically::

            from flask import url_for, Response
            from changedetectionio.pluggy_interface import hookimpl
            from changedetectionio.flask_app import app as _app

            MY_CSS = ".my-module-example { color: red; }"
            MY_JS  = "console.log('my_module_content loaded');"

            @_app.route('/my_module_content/css')
            def my_module_content_css():
                return Response(MY_CSS, mimetype='text/css',
                                headers={'Cache-Control': 'max-age=3600'})

            @_app.route('/my_module_content/js')
            def my_module_content_js():
                return Response(MY_JS, mimetype='application/javascript',
                                headers={'Cache-Control': 'max-age=3600'})

            @hookimpl
            def get_html_head_extras(self):
                css = url_for('my_module_content_css')
                js  = url_for('my_module_content_js')
                return (
                    f'<link rel="stylesheet" href="{css}">\\n'
                    f'<script src="{js}" defer></script>'
                )

        Returns:
            str or None: Raw HTML string to inject inside <head>, or None
        """
        pass

    # --- Browser lifecycle (see changedetectionio/browser_lifecycle.py for the whole picture) ---

    @hookspec
    def browser_config_form_section(base_fetcher, capabilities):
        """Add a section to the edit page of a browser built on `base_fetcher`.

        Args:
            base_fetcher: the engine the browser is built on, e.g. 'html_webdriver', 'html_requests'
            capabilities: that engine's FetcherCapabilities as a dict ('supports_screenshots' etc)

        Returns:
            changedetectionio.plugin_api.BrowserConfigSection, or None to add nothing for this
            engine. What the user saves is stored with the browser and comes back at fetch time as
            request.plugin_settings(plugin_id) / browser_config.plugin_config(plugin_id).
        """
        pass

    @hookspec
    def browser_request_alter(request, watch, datastore):
        """Change what is about to be handed to the browser, in place.

        Called before every check, and before a live Browser Steps session starts
        (request.purpose == 'browser_steps'). `request` is a BrowserRequest: change
        request.headers, request.cookies, request.proxy_url, request.method, request.body, or keep
        state for browser_request_finished() in request.extra. May be `async def`.

        Raising stops the fetch and the exception message becomes the watch's error.
        """
        pass

    @hookspec
    def browser_request_finished(request, fetcher, error, watch, datastore):
        """Called after the browser has run, also when it failed, and when a live Browser Steps
        session is cleaned up. For cleanup: request.fetcher_name says which engine ran.

        Args:
            request: the BrowserRequest as it was after browser_request_alter()
            fetcher: the content fetcher instance (status_code, content, ...), None for a live session
            error:   the exception the fetch raised, or None
        May be `async def`. Exceptions are logged and never reach the caller.
        """
        pass

    # --- Watch / group / system settings and engine overrides (see changedetectionio/plugin_settings.py) ---

    @hookspec
    def settings_form_section(scope):
        """Add a section to a settings page.

        Args:
            scope: 'watch' (watch edit page, Request tab), 'tag' (group edit page, Browser tab) or
                   'global' (Settings, Fetching tab)

        Returns:
            changedetectionio.plugin_api.SettingsSection, or None. What the user saves is stored as
            plugin_settings[plugin_id] on the watch, the group, or in the system settings; read the
            combined value with plugin_api.resolved_plugin_settings(watch, plugin_id).
        """
        pass

    @hookspec(firstresult=True)
    def fetch_engine_override(watch, engine):
        """Fetch this watch with a different engine than the one its browser resolves to.

        Called both when fetching and when working out what the watch's browser can do (so the edit
        page hides the Visual Selector etc. for an engine that can't), so keep it cheap: read the
        watch and settings, no network or disk.

        Args:
            watch:  the watch
            engine: the engine name its browser resolves to, e.g. 'html_webdriver'

        Returns:
            Another registered engine name (e.g. 'html_flaresolverr'), or None to leave it.
        """
        pass

    @hookspec
    def watch_list_extra_text(watch):
        """Short plain-text notes shown under the watch in the watch list (class extra-watch-text).

        Returns:
            str, a list of str, or None. Escaped when rendered.
        """
        pass

    # --- Conditions (JSON Logic rules on the watch edit page) ---

    @hookspec
    def register_operators():
        """Return a dict of extra JSON Logic operators, {"operator_name": callable}."""
        pass

    @hookspec
    def register_operator_choices():
        """Return a list of (operator_name, label) tuples to offer in the conditions UI."""
        pass

    @hookspec
    def register_field_choices():
        """Return a list of (field_name, label) tuples to offer in the conditions UI."""
        pass

    @hookspec
    def add_data(current_watch_uuid, application_datastruct, ephemeral_data):
        """Return a dict of extra facts the conditions are evaluated against.

        Each implementation is given 10 seconds, see conditions.execute_ruleset_against_all_plugins().
        """
        pass


_plugin_health = {}
_plugin_health_lock = threading.Lock()


def _record_hook_success(plugin_name):
    with _plugin_health_lock:
        health = _plugin_health.get(plugin_name)
        if health:
            health['consecutive_failures'] = 0


def _record_hook_failure(plugin_name, hook_name, exception):
    with _plugin_health_lock:
        health = _plugin_health.setdefault(plugin_name, {'consecutive_failures': 0, 'total_failures': 0})
        health['consecutive_failures'] += 1
        health['total_failures'] += 1
        health['last_hook'] = hook_name
        health['last_error'] = f"{type(exception).__name__}: {exception}"
        health['last_error_time'] = time.time()
    logger.opt(exception=exception).error(f"Plugin '{plugin_name}' raised in hook '{hook_name}': {exception}")


def get_plugin_health(plugin_name=None):
    """Failure counters per plugin, {name: {'consecutive_failures', 'total_failures', 'last_hook',
    'last_error', 'last_error_time', 'errored'}}. Plugins that never failed are not listed."""
    with _plugin_health_lock:
        snapshot = {name: dict(h, errored=h['consecutive_failures'] >= PLUGIN_CONSECUTIVE_FAILURES_ERRORED)
                    for name, h in _plugin_health.items()}
    if plugin_name is not None:
        return snapshot.get(plugin_name)
    return snapshot


def _isolate_hookimpl(function, plugin_name, hook_name):
    """Wrap one hook implementation so its exceptions are logged and counted instead of breaking
    the hook call (and with it the check, page or worker that made it).

    pluggy calls hookimpl.function(*args) with the arguments the implementation declared, and it
    has already read those names (HookImpl.argnames) from the original function, so the wrapper
    only has to pass everything through.
    """
    propagate = hook_name in HOOKS_THAT_PROPAGATE_EXCEPTIONS

    if inspect.iscoroutinefunction(function):
        import asyncio

        @wraps(function)
        async def isolated_async(*args, **kwargs):
            try:
                result = await asyncio.wait_for(function(*args, **kwargs), timeout=PLUGIN_ASYNC_HOOK_TIMEOUT)
            except Exception as e:
                _record_hook_failure(plugin_name, hook_name, e)
                if propagate:
                    raise
                return None
            _record_hook_success(plugin_name)
            return result

        return isolated_async

    @wraps(function)
    def isolated(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
        except Exception as e:
            _record_hook_failure(plugin_name, hook_name, e)
            if propagate:
                raise
            return None
        _record_hook_success(plugin_name)
        return result

    return isolated


class ChangeDetectionPluginManager(pluggy.PluginManager):
    """pluggy.PluginManager with failure isolation and the legacy conditions hookimpl marker."""

    _warned_legacy_marker = set()

    def parse_hookimpl_opts(self, plugin, name):
        opts = super().parse_hookimpl_opts(plugin, name)
        if opts is None:
            method = getattr(plugin, name, None)
            if inspect.isroutine(method):
                legacy = getattr(method, LEGACY_CONDITIONS_NAMESPACE + "_impl", None)
                if isinstance(legacy, dict):
                    plugin_label = getattr(plugin, '__name__', type(plugin).__name__)
                    if plugin_label not in self._warned_legacy_marker:
                        self._warned_legacy_marker.add(plugin_label)
                        logger.warning(f"Plugin '{plugin_label}' uses the deprecated "
                                       f"HookimplMarker('{LEGACY_CONDITIONS_NAMESPACE}'), "
                                       f"use 'from changedetectionio.plugin_api import hookimpl' instead")
                    opts = dict(legacy)
        return opts

    def register(self, plugin, name=None):
        plugin_name = super().register(plugin, name)
        if plugin_name is None:
            return None
        for hook_caller in self.get_hookcallers(plugin) or []:
            for impl in hook_caller.get_hookimpls():
                # Wrappers are generators that pluggy drives itself, leave them alone
                if impl.plugin is plugin and not (impl.wrapper or impl.hookwrapper):
                    impl.function = _isolate_hookimpl(impl.function, plugin_name, hook_caller.name)
        return plugin_name


# Set up Plugin Manager
plugin_manager = ChangeDetectionPluginManager(PLUGIN_NAMESPACE)

# Register hookspecs
plugin_manager.add_hookspecs(ChangeDetectionSpec)

# Load plugins from subdirectories
def load_plugins_from_directories():
    # The built-in conditions operators (starts_with, length_min, ...), first so its choices lead the lists
    from changedetectionio.conditions import default_plugin
    if not plugin_manager.is_registered(default_plugin):
        plugin_manager.register(default_plugin, 'conditions_default_plugin')

    # List of (python_package_prefix, filesystem_path) pairs to scan for plugins.
    # NOTE: processors/restock_diff/plugins is intentionally excluded here — those
    # plugins are registered via register_builtin_restock_plugins() to avoid the
    # circular import: restock_diff/__init__.py → model.Watch → content_fetchers → pluggy_interface.
    plugin_dirs = [
        (
            'changedetectionio.conditions.plugins',
            os.path.join(os.path.dirname(__file__), 'conditions', 'plugins'),
        ),
    ]

    for module_prefix, dir_path in plugin_dirs:
        if not os.path.exists(dir_path):
            continue

        # Get all Python files (excluding __init__.py)
        for filename in os.listdir(dir_path):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]  # Remove .py extension
                module_path = f"{module_prefix}.{module_name}"

                try:
                    module = importlib.import_module(module_path)
                    # Register the plugin with pluggy
                    plugin_manager.register(module, module_name)
                except (ImportError, AttributeError) as e:
                    print(f"Error loading plugin {module_name}: {e}")


# Load plugins
load_plugins_from_directories()

# Discover installed plugins from external packages (if any)
plugin_manager.load_setuptools_entrypoints(PLUGIN_NAMESPACE)
# Conditions plugins published before the hook namespaces were merged
plugin_manager.load_setuptools_entrypoints(LEGACY_CONDITIONS_NAMESPACE)

# Function to inject datastore into plugins that need it
def inject_datastore_into_plugins(datastore):
    """Inject the global datastore into plugins that need access to settings.

    This should be called after plugins are loaded and datastore is initialized.

    Args:
        datastore: The global ChangeDetectionStore instance
    """
    for plugin_name, plugin_obj in plugin_manager.list_name_plugin():
        # Check if plugin has datastore attribute and it's not set
        if hasattr(plugin_obj, 'datastore'):
            if plugin_obj.datastore is None:
                plugin_obj.datastore = datastore
                logger.debug(f"Injected datastore into plugin: {plugin_name}")

# Function to register built-in fetchers - called later from content_fetchers/__init__.py
def register_builtin_fetchers():
    """Register built-in content fetchers as internal plugins

    This is called from content_fetchers/__init__.py after all fetchers are imported
    to avoid circular import issues.
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers import requests, playwright, puppeteer, webdriver_selenium, html_debug_test_browser

    # These builtin plugins are registered AFTER content_fetchers finished importing (and after
    # get_plugin_fetchers() ran its setattr pass), so their classes aren't module attributes yet.
    # resolve_content_fetcher() resolves engines via getattr(content_fetchers, name), so expose
    # them explicitly here.
    def _register_fetcher(plugin, plugin_name, fetcher_key, fetcher_cls):
        plugin_manager.register(plugin, plugin_name)
        setattr(content_fetchers, fetcher_key, fetcher_cls)

    # Register each built-in fetcher plugin
    if hasattr(requests, 'requests_plugin'):
        plugin_manager.register(requests.requests_plugin, 'builtin_requests')

    # Debug/test fetcher - echoes the resolved browser config as JSON content. Opt-in only via
    # ENABLE_DEBUG_CONTENT_FETCHER (never registered in production).
    # Enables strong end-to-end pipeline tests without a real browser.
    import os
    from changedetectionio.strtobool import strtobool
    if strtobool(os.getenv('ENABLE_DEBUG_CONTENT_FETCHER', 'False')) \
            and hasattr(html_debug_test_browser, 'debug_test_browser_plugin'):
        _register_fetcher(html_debug_test_browser.debug_test_browser_plugin, 'builtin_debug_test_browser',
                          'html_debug_test_browser', html_debug_test_browser.fetcher)
        logger.info("Registered debug content fetcher (ENABLE_DEBUG_CONTENT_FETCHER)")

    # html_playwright_builtin - local Playwright launch, only when the playwright library is
    # importable (no env default; opt-in via a browser config).
    try:
        import playwright as _playwright_lib  # noqa: F401
        from changedetectionio.content_fetchers import playwright_builtin
        if hasattr(playwright_builtin, 'playwright_builtin_plugin'):
            _register_fetcher(playwright_builtin.playwright_builtin_plugin, 'builtin_playwright_builtin',
                              'html_playwright_builtin', playwright_builtin.fetcher)
    except ImportError:
        logger.debug("playwright library not installed - html_playwright_builtin fetcher not offered")

    # html_external_cdp - an external CDP-over-WebSocket browser named by each browser config.
    # Registered UNCONDITIONALLY, unlike html_playwright_builtin: saved browser configs (including
    # every extra browser migrated by update_36) name this engine, so it has to resolve even where
    # the playwright library is absent - resolve_content_fetcher() would otherwise fall through to
    # the plain HTTP client and silently fetch those watches with the wrong thing. The library is
    # imported lazily inside run(), so a missing install surfaces as a clear error at fetch time.
    from changedetectionio.content_fetchers import external_cdp
    if hasattr(external_cdp, 'external_cdp_plugin'):
        _register_fetcher(external_cdp.external_cdp_plugin, 'builtin_external_cdp',
                          'html_external_cdp', external_cdp.fetcher)

    if hasattr(playwright, 'playwright_plugin'):
        plugin_manager.register(playwright.playwright_plugin, 'builtin_playwright')

    if hasattr(puppeteer, 'puppeteer_plugin'):
        plugin_manager.register(puppeteer.puppeteer_plugin, 'builtin_puppeteer')

    if hasattr(webdriver_selenium, 'webdriver_selenium_plugin'):
        plugin_manager.register(webdriver_selenium.webdriver_selenium_plugin, 'builtin_webdriver_selenium')


def register_builtin_restock_plugins():
    """Register built-in restock processor plugins after all imports are complete.

    Called from content_fetchers/__init__.py alongside register_builtin_fetchers()
    to avoid the circular import that occurs when loading via load_plugins_from_directories()
    (restock_diff/__init__.py → model.Watch → content_fetchers → pluggy_interface).
    """
    import importlib
    module_path = 'changedetectionio.processors.restock_diff.plugins.llm_restock'
    try:
        module = importlib.import_module(module_path)
        if not plugin_manager.is_registered(module):
            plugin_manager.register(module, 'llm_restock')
            logger.debug("Registered built-in restock plugin: llm_restock")
    except Exception as e:
        logger.error(f"Failed to register llm_restock plugin: {e}")

# Helper function to collect UI stats extras from all plugins
def collect_ui_edit_stats_extras(watch):
    """Collect and combine HTML content from all plugins that implement ui_edit_stats_extras"""
    extras_content = []

    # Get all plugins that implement the ui_edit_stats_extras hook
    results = plugin_manager.hook.ui_edit_stats_extras(watch=watch)

    # If we have results, add them to our content
    if results:
        for result in results:
            if result:  # Skip empty results
                extras_content.append(result)

    return "\n".join(extras_content) if extras_content else ""

def collect_fetcher_status_icons(fetcher_name):
    """Collect status icon data from all plugins

    Args:
        fetcher_name: The name of the fetcher (e.g., 'html_webdriver', 'html_js_zyte')

    Returns:
        dict or None: Icon data dictionary from first matching plugin, or None
    """
    # Get status icon data from plugins
    results = plugin_manager.hook.fetcher_status_icon(fetcher_name=fetcher_name)

    # Return first non-None result
    if results:
        for result in results:
            if result and isinstance(result, dict):
                return result

    return None

def get_itemprop_availability_from_plugin(content, fetcher_name, fetcher_instance, url, llm_intent=None):
    """Get itemprop availability data from plugins as a fallback.

    This is called when the built-in get_itemprop_availability doesn't find good data.

    Args:
        content: The HTML/text content to parse
        fetcher_name: The name of the fetcher being used (e.g., 'html_js_zyte')
        fetcher_instance: The fetcher instance that generated the content
        url: The URL being watched (watch.link - includes Jinja2 evaluation)
        llm_intent: Optional user-supplied intent string passed through to plugins

    Returns:
        dict or None: Availability data dictionary from first matching plugin, or None
    """
    hook = plugin_manager.hook.get_itemprop_availability_override

    # html_to_text() isn't free on a large product page, so only run it when some
    # implementation actually asks for `text` (pluggy only passes the args an impl declares).
    text = None
    if content and any('text' in impl.argnames for impl in hook.get_hookimpls()):
        try:
            from changedetectionio.html_tools import html_to_text
            text = html_to_text(content)
        except Exception as e:
            logger.warning(f"Could not convert {url} to text for restock plugins: {e}")

    # firstresult=True, so this is the first non-None answer
    result = hook(
        content=content,
        fetcher_name=fetcher_name,
        fetcher_instance=fetcher_instance,
        url=url,
        llm_intent=llm_intent,
        text=text,
    )

    # Only accept it if it carries actual data
    if result and isinstance(result, dict):
        if result.get('price') is not None or result.get('availability'):
            return result

    return None


def get_active_plugins():
    """Get a list of active plugins with their descriptions.

    Returns:
        list: List of dictionaries with plugin information:
            [
                {'name': 'plugin_name', 'description': 'Plugin description'},
                ...
            ]
    """
    active_plugins = []

    # Get all registered plugins
    for plugin_name, plugin_obj in plugin_manager.list_name_plugin():
        # Skip built-in plugins (they start with 'builtin_')
        if plugin_name.startswith('builtin_'):
            continue

        # Get plugin description if available
        description = None
        if hasattr(plugin_obj, '__doc__') and plugin_obj.__doc__:
            description = plugin_obj.__doc__.strip().split('\n')[0]  # First line only
        elif hasattr(plugin_obj, 'description'):
            description = plugin_obj.description

        # Try to get a friendly name from the plugin
        friendly_name = plugin_name
        if hasattr(plugin_obj, 'name'):
            friendly_name = plugin_obj.name

        active_plugins.append({
            'name': friendly_name,
            'description': description or 'No description available'
        })

    return active_plugins


def get_fetcher_capabilities(watch, datastore):
    """Get capability flags for a watch's fetcher.

    Args:
        watch: The watch object/dict
        datastore: The datastore to resolve 'system' fetcher

    Returns:
        dict: Dictionary with capability flags:
            {
                'supports_browser_steps': bool,
                'supports_screenshots': bool,
                'supports_xpath_element_data': bool
            }
    """
    # The effective engine that will fetch this watch (honours a group override + browser-config
    # id + 'system'), so capability checks (Visual Selector etc.) reflect reality.
    from changedetectionio.model.browser_config import resolve_watch_fetcher_engine
    fetcher_name = resolve_watch_fetcher_engine(watch, datastore)

    # Get the fetcher class
    from changedetectionio import content_fetchers

    # Try built-in fetchers first, then plugin-provided fetchers
    fetcher_class = None
    if hasattr(content_fetchers, fetcher_name):
        fetcher_class = getattr(content_fetchers, fetcher_name)
    else:
        # Query all plugins for registered fetchers
        for fetcher_registration in plugin_manager.hook.register_content_fetcher():
            if fetcher_registration and fetcher_registration[0] == fetcher_name:
                fetcher_class = fetcher_registration[1]
                break

    # Log + build from the shared FetcherCapabilities model. Return a plain dict so
    # callers (e.g. blueprint/ui/edit.py) can still add their own extra capability keys.
    caps = content_fetchers._log_fetcher_capabilities(fetcher_class, fetcher_name, uuid=watch.get('uuid'))
    return caps.model_dump()


def get_plugin_settings_tabs():
    """Get all plugin settings tabs.

    Returns:
        list: List of dictionaries with plugin settings tab information:
            [
                {
                    'plugin_id': str,
                    'tab_label': str,
                    'form_class': Form,
                    'description': str
                },
                ...
            ]
    """
    tabs = []
    results = plugin_manager.hook.plugin_settings_tab()

    for result in results:
        if result and isinstance(result, dict):
            # Validate required fields
            if 'plugin_id' in result and 'tab_label' in result and 'form_class' in result:
                tabs.append(result)
            else:
                logger.warning(f"Invalid plugin settings tab spec: {result}")

    return tabs


def load_plugin_settings(datastore_path, plugin_id):
    """Load settings for a specific plugin from JSON file.

    Args:
        datastore_path: Path to the datastore directory
        plugin_id: Unique identifier for the plugin (e.g., 'zyte_fetcher')

    Returns:
        dict: Plugin settings, or empty dict if file doesn't exist
    """
    import json
    settings_file = os.path.join(datastore_path, f"{plugin_id}.json")

    if not os.path.exists(settings_file):
        return {}

    try:
        with open(settings_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load settings for plugin '{plugin_id}': {e}")
        return {}


def save_plugin_settings(datastore_path, plugin_id, settings):
    """Save settings for a specific plugin to JSON file.

    Args:
        datastore_path: Path to the datastore directory
        plugin_id: Unique identifier for the plugin (e.g., 'zyte_fetcher')
        settings: Dictionary of settings to save

    Returns:
        bool: True if save was successful, False otherwise
    """
    import json
    settings_file = os.path.join(datastore_path, f"{plugin_id}.json")

    try:
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved settings for plugin '{plugin_id}' to {settings_file}")
        return True
    except Exception as e:
        logger.error(f"Failed to save settings for plugin '{plugin_id}': {e}")
        return False


def get_plugin_template_paths():
    """Get list of plugin template directories for Jinja2 loader.

    Scans both external pluggy plugins and built-in processor plugins.

    Returns:
        list: List of absolute paths to plugin template directories
    """
    template_paths = []

    # Add the base processors/templates directory (as absolute path)
    processors_templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processors', 'templates')
    if os.path.isdir(processors_templates_dir):
        template_paths.append(processors_templates_dir)
        logger.debug(f"Added base processors template path: {processors_templates_dir}")

    # Scan built-in processor plugins
    from changedetectionio.processors import find_processors
    processor_list = find_processors()
    for processor_module, processor_name in processor_list:
        # Each processor is a module, check if it has a templates directory
        if hasattr(processor_module, '__file__'):
            processor_file = processor_module.__file__
            if processor_file:
                # Get the processor directory (e.g., processors/image_ssim_diff/)
                processor_dir = os.path.dirname(os.path.abspath(processor_file))
                templates_dir = os.path.join(processor_dir, 'templates')
                if os.path.isdir(templates_dir):
                    template_paths.append(templates_dir)
                    logger.debug(f"Added processor template path: {templates_dir}")

    # Get all registered external pluggy plugins
    for plugin_name, plugin_obj in plugin_manager.list_name_plugin():
        # Check if plugin has a templates directory
        if hasattr(plugin_obj, '__file__'):
            plugin_file = plugin_obj.__file__
        elif hasattr(plugin_obj, '__module__'):
            # Get the module file
            module = sys.modules.get(plugin_obj.__module__)
            if module and hasattr(module, '__file__'):
                plugin_file = module.__file__
            else:
                continue
        else:
            continue

        if plugin_file:
            plugin_dir = os.path.dirname(os.path.abspath(plugin_file))
            templates_dir = os.path.join(plugin_dir, 'templates')
            if os.path.isdir(templates_dir):
                template_paths.append(templates_dir)
                logger.debug(f"Added plugin template path: {templates_dir}")

    return template_paths


def apply_update_handler_alter(update_handler, watch, datastore):
    """Apply update_handler_alter hooks from all plugins.

    Allows plugins to wrap or modify the update_handler before it processes a watch.
    Multiple plugins can chain modifications - each plugin receives the result from
    the previous plugin.

    Args:
        update_handler: The perform_site_check instance to potentially modify
        watch: The watch dict being processed
        datastore: The application datastore

    Returns:
        object: The (potentially modified/wrapped) update_handler
    """
    # Get all plugins that implement the update_handler_alter hook
    results = plugin_manager.hook.update_handler_alter(
        update_handler=update_handler,
        watch=watch,
        datastore=datastore
    )

    # Chain results - each plugin gets the result from the previous one
    current_handler = update_handler
    if results:
        for result in results:
            if result is not None:
                logger.debug(f"Plugin modified update_handler for watch {watch.get('uuid')}")
                current_handler = result

    return current_handler


def apply_update_finalize(update_handler, watch, datastore, processing_exception):
    """Apply update_finalize hooks from all plugins.

    Called in the finally block after watch processing completes, allowing plugins
    to perform cleanup, update metrics, or log final status.

    Args:
        update_handler: The perform_site_check instance (may be None)
        watch: The watch dict that was processed (may be None)
        datastore: The application datastore
        processing_exception: The exception from processing, or None if successful

    Returns:
        None
    """
    try:
        # Call all plugins that implement the update_finalize hook
        plugin_manager.hook.update_finalize(
            update_handler=update_handler,
            watch=watch,
            datastore=datastore,
            processing_exception=processing_exception
        )
    except Exception as e:
        # Don't let plugin errors crash the worker
        logger.error(f"Error in update_finalize hook: {e}")
        logger.exception(f"update_finalize hook exception details:")


def collect_html_head_extras():
    """Collect and combine HTML head extras from all plugins.

    Called from a Flask template global so it always runs inside a request context.
    This means url_for() works correctly in plugin implementations, including when the
    app is deployed under a sub-path via USE_X_SETTINGS / X-Forwarded-Prefix (ProxyFix
    sets SCRIPT_NAME so url_for() automatically prepends the prefix).

    Returns:
        str: Combined HTML string to inject inside <head>, or empty string
    """
    results = plugin_manager.hook.get_html_head_extras()
    parts = [r for r in results if r]
    return "\n".join(parts) if parts else ""