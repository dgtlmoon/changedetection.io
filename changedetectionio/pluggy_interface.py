import pluggy
import os
import importlib
import sys

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