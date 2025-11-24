import pluggy
import os
import importlib
import sys
from loguru import logger

# Global plugin namespace for changedetection.io
PLUGIN_NAMESPACE = "changedetectionio"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)


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

    @hookspec
    def get_itemprop_availability_override(self, content, fetcher_name, fetcher_instance, url):
        """Provide custom implementation of get_itemprop_availability for a specific fetcher.

        This hook allows plugins to provide their own product availability detection
        when their fetcher is being used. This is called as a fallback when the built-in
        method doesn't find good data.

        Args:
            content: The HTML/text content to parse
            fetcher_name: The name of the fetcher being used (e.g., 'html_js_zyte')
            fetcher_instance: The fetcher instance that generated the content
            url: The URL being watched/checked

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


# Set up Plugin Manager
plugin_manager = pluggy.PluginManager(PLUGIN_NAMESPACE)

# Register hookspecs
plugin_manager.add_hookspecs(ChangeDetectionSpec)

# Load plugins from subdirectories
def load_plugins_from_directories():
    # Dictionary of directories to scan for plugins
    plugin_dirs = {
        'conditions': os.path.join(os.path.dirname(__file__), 'conditions', 'plugins'),
        # Add more plugin directories here as needed
    }
    
    # Note: Removed the direct import of example_word_count_plugin as it's now in the conditions/plugins directory
    
    for dir_name, dir_path in plugin_dirs.items():
        if not os.path.exists(dir_path):
            continue
            
        # Get all Python files (excluding __init__.py)
        for filename in os.listdir(dir_path):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]  # Remove .py extension
                module_path = f"changedetectionio.{dir_name}.plugins.{module_name}"
                
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
    from changedetectionio.content_fetchers import requests, playwright, puppeteer, webdriver_selenium

    # Register each built-in fetcher plugin
    if hasattr(requests, 'requests_plugin'):
        plugin_manager.register(requests.requests_plugin, 'builtin_requests')

    if hasattr(playwright, 'playwright_plugin'):
        plugin_manager.register(playwright.playwright_plugin, 'builtin_playwright')

    if hasattr(puppeteer, 'puppeteer_plugin'):
        plugin_manager.register(puppeteer.puppeteer_plugin, 'builtin_puppeteer')

    if hasattr(webdriver_selenium, 'webdriver_selenium_plugin'):
        plugin_manager.register(webdriver_selenium.webdriver_selenium_plugin, 'builtin_webdriver_selenium')

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

def get_itemprop_availability_from_plugin(content, fetcher_name, fetcher_instance, url):
    """Get itemprop availability data from plugins as a fallback.

    This is called when the built-in get_itemprop_availability doesn't find good data.

    Args:
        content: The HTML/text content to parse
        fetcher_name: The name of the fetcher being used (e.g., 'html_js_zyte')
        fetcher_instance: The fetcher instance that generated the content
        url: The URL being watched (watch.link - includes Jinja2 evaluation)

    Returns:
        dict or None: Availability data dictionary from first matching plugin, or None
    """
    # Get availability data from plugins
    results = plugin_manager.hook.get_itemprop_availability_override(
        content=content,
        fetcher_name=fetcher_name,
        fetcher_instance=fetcher_instance,
        url=url
    )

    # Return first non-None result with actual data
    if results:
        for result in results:
            if result and isinstance(result, dict):
                # Check if the result has any meaningful data
                if result.get('price') is not None or result.get('availability'):
                    return result

    return None


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
    # Get the fetcher name from watch
    fetcher_name = watch.get('fetch_backend', 'system')

    # Resolve 'system' to actual fetcher
    if fetcher_name == 'system':
        fetcher_name = datastore.data['settings']['application'].get('fetch_backend', 'html_requests')

    # Get the fetcher class
    from changedetectionio import content_fetchers

    # Try to get from built-in fetchers first
    if hasattr(content_fetchers, fetcher_name):
        fetcher_class = getattr(content_fetchers, fetcher_name)
        return {
            'supports_browser_steps': getattr(fetcher_class, 'supports_browser_steps', False),
            'supports_screenshots': getattr(fetcher_class, 'supports_screenshots', False),
            'supports_xpath_element_data': getattr(fetcher_class, 'supports_xpath_element_data', False)
        }

    # Try to get from plugin-provided fetchers
    # Query all plugins for registered fetchers
    plugin_fetchers = plugin_manager.hook.register_content_fetcher()
    for fetcher_registration in plugin_fetchers:
        if fetcher_registration:
            name, fetcher_class = fetcher_registration
            if name == fetcher_name:
                return {
                    'supports_browser_steps': getattr(fetcher_class, 'supports_browser_steps', False),
                    'supports_screenshots': getattr(fetcher_class, 'supports_screenshots', False),
                    'supports_xpath_element_data': getattr(fetcher_class, 'supports_xpath_element_data', False)
                }

    # Default: no capabilities
    return {
        'supports_browser_steps': False,
        'supports_screenshots': False,
        'supports_xpath_element_data': False
    }