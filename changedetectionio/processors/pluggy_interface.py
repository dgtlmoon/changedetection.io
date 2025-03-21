import pluggy
from loguru import logger

# Ensure that the namespace in HookspecMarker matches PluginManager
PLUGIN_NAMESPACE = "changedetectionio_processors"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)

UI_tags = {}

class ProcessorSpec:
    """Hook specifications for difference detection processors."""

    @hookspec
    def get_processor_name():
        """Return the processor name for selection in the UI."""
        pass

    @hookspec
    def get_processor_description():
        """Return a human-readable description of the processor."""
        pass
        
    @hookspec
    def get_processor_version():
        """Return the processor plugin version."""
        pass
    
    @hookspec
    def get_processor_ui_tag():
        """Return the UI tag for the processor (used for categorization in UI)."""
        pass
    
    @hookspec
    def perform_site_check(datastore, watch_uuid):
        """Return the processor handler class or None if not applicable.
        
        Each plugin should check if it's the right processor for this watch
        and return None if it's not.
        
        Should return an instance of a class that implements:
        - call_browser(preferred_proxy_id=None): Fetch the content
        - run_changedetection(watch): Analyze for changes and return tuple of (changed_detected, update_obj, contents)
        """
        pass
    
    @hookspec
    def get_form_class(processor_name):
        """Return the WTForms form class for the processor settings or None if not applicable.
        
        Each plugin should check if it's the right processor and return None if not.
        """
        pass

    @hookspec
    def get_watch_model_class(processor_name):
        """Return a custom Watch model class if needed or None if not applicable.
        
        Each plugin should check if it's the right processor and return None if not.
        """
        pass

# Set up Pluggy Plugin Manager
plugin_manager = pluggy.PluginManager(PLUGIN_NAMESPACE)

# Register hookspecs
plugin_manager.add_hookspecs(ProcessorSpec)

# Initialize by loading plugins and building UI_tags dictionary
try:
    # Discover installed plugins from external packages (if any)
    plugin_manager.load_setuptools_entrypoints(PLUGIN_NAMESPACE)
    logger.info(f"Loaded plugins: {plugin_manager.get_plugins()}")
    
    # Build UI_tags dictionary from all plugins
    for plugin in plugin_manager.get_plugins():
        if hasattr(plugin, "get_processor_name") and hasattr(plugin, "get_processor_ui_tag"):
            plugin_name = plugin.get_processor_name()
            ui_tag = plugin.get_processor_ui_tag()
            if plugin_name and ui_tag:
                UI_tags[plugin_name] = ui_tag
                logger.info(f"Found UI tag for plugin {plugin_name}: {ui_tag}")
except Exception as e:
    logger.critical(f"Error loading plugins: {str(e)}")