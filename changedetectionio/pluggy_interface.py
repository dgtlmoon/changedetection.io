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