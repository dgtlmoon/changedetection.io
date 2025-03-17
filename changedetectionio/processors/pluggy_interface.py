import pluggy

# Define the plugin namespace for processors
PLUGIN_NAMESPACE = "changedetectionio_processors"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)


class ProcessorSpec:
    """Hook specifications for processor plugins."""

    @hookspec
    def get_processor_name():
        """Return the name of the processor."""
        pass

    @hookspec
    def get_processor_description():
        """Return the description of the processor."""
        pass
    
    @hookspec
    def get_processor_class():
        """Return the processor class."""
        pass
    
    @hookspec
    def get_processor_form():
        """Return the processor form class."""
        pass
    
    @hookspec
    def get_processor_watch_model():
        """Return the watch model class for this processor (if any)."""
        pass
    
    @hookspec
    def get_display_link(url, processor_name):
        """Return a custom display link for the given processor.
        
        Args:
            url: The original URL from the watch
            processor_name: The name of the processor
            
        Returns:
            A string with the custom display link or None to use the default
        """
        pass
    
    @hookspec
    def perform_site_check(datastore, watch_uuid):
        """Create and return a processor instance ready to perform site check.
        
        Args:
            datastore: The application datastore
            watch_uuid: The UUID of the watch to check
            
        Returns:
            A processor instance ready to perform site check
        """
        pass


# Set up the plugin manager
plugin_manager = pluggy.PluginManager(PLUGIN_NAMESPACE)

# Register hook specifications
plugin_manager.add_hookspecs(ProcessorSpec)