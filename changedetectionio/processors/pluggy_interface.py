import pluggy

# Ensure that the namespace in HookspecMarker matches PluginManager
PLUGIN_NAMESPACE = "changedetectionio_processors"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)


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

# Discover installed plugins from external packages (if any)
plugin_manager.load_setuptools_entrypoints(PLUGIN_NAMESPACE)