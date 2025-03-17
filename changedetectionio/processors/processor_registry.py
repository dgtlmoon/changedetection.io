from loguru import logger
from changedetectionio.model import Watch
from .pluggy_interface import plugin_manager

# Register the WHOIS plugin
from . import whois_plugin
plugin_manager.register(whois_plugin)

# Load any setuptools entrypoints
plugin_manager.load_setuptools_entrypoints("changedetectionio_processors")

def register_plugin(plugin_module):
    """Register a processor plugin"""
    plugin_manager.register(plugin_module)

def get_all_processors():
    """Get all processors
    :return: List of tuples (processor_name, processor_description)
    """
    processors = []
    
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # Get the processor description from this plugin
            description = plugin_manager.hook.get_processor_description(plugin=plugin)
            
            # Check if both name and description were returned
            if name and description:
                # Each plugin should return exactly one name and one description
                processors.append((name[0], description[0]))
        except Exception as e:
            logger.error(f"Error getting processor info from plugin: {str(e)}")
    
    return processors

def get_processor_class(processor_name):
    """Get processor class by name
    :param processor_name: Name of the processor
    :return: Processor class or None
    """
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # If this plugin's processor name matches what we're looking for
            if name and name[0] == processor_name:
                # Get the processor class
                processor_class = plugin_manager.hook.get_processor_class(plugin=plugin)
                if processor_class:
                    return processor_class[0]
        except Exception as e:
            logger.error(f"Error getting processor class from plugin: {str(e)}")
    
    return None

def get_processor_form(processor_name):
    """Get processor form by name
    :param processor_name: Name of the processor
    :return: Processor form class or None
    """
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # If this plugin's processor name matches what we're looking for
            if name and name[0] == processor_name:
                # Get the processor form
                processor_form = plugin_manager.hook.get_processor_form(plugin=plugin)
                if processor_form:
                    return processor_form[0]
        except Exception as e:
            logger.error(f"Error getting processor form from plugin: {str(e)}")
    
    return None

def get_processor_watch_model(processor_name):
    """Get processor watch model by name
    :param processor_name: Name of the processor
    :return: Watch model class or default Watch model
    """
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # If this plugin's processor name matches what we're looking for
            if name and name[0] == processor_name:
                # Get the processor watch model
                processor_watch_model = plugin_manager.hook.get_processor_watch_model(plugin=plugin)
                if processor_watch_model and processor_watch_model[0]:
                    return processor_watch_model[0]
        except Exception as e:
            logger.error(f"Error getting processor watch model from plugin: {str(e)}")
    
    return Watch.model


def get_processor_site_check(processor_name, datastore, watch_uuid):
    """Get a processor instance ready to perform site check
    :param processor_name: Name of the processor
    :param datastore: The application datastore
    :param watch_uuid: The UUID of the watch to check
    :return: A processor instance ready to perform site check, or None
    """
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # If this plugin's processor name matches what we're looking for
            if name and name[0] == processor_name:
                # Try to get the perform_site_check implementation
                perform_site_check_impls = plugin_manager.hook.perform_site_check(
                    plugin=plugin,
                    datastore=datastore,
                    watch_uuid=watch_uuid
                )
                if perform_site_check_impls:
                    return perform_site_check_impls[0]
                
                # If no perform_site_check hook implementation, try getting the class and instantiating it
                processor_class = plugin_manager.hook.get_processor_class(plugin=plugin)
                if processor_class:
                    return processor_class[0](datastore=datastore, watch_uuid=watch_uuid)
        except Exception as e:
            logger.error(f"Error getting processor site check from plugin: {str(e)}")
    
    return None


def get_display_link(url, processor_name):
    """Get a custom display link for the given processor
    :param url: The original URL from the watch
    :param processor_name: Name of the processor
    :return: A string with the custom display link or None to use the default
    """
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            # If this plugin's processor name matches what we're looking for
            if name and name[0] == processor_name:
                # Try to get the get_display_link implementation
                display_links = plugin_manager.hook.get_display_link(
                    plugin=plugin,
                    url=url,
                    processor_name=processor_name
                )
                if display_links and display_links[0]:
                    return display_links[0]
        except Exception as e:
            logger.error(f"Error getting display link from plugin: {str(e)}")
    
    return None


def get_plugin_processor_modules():
    """Get processor modules for all plugins that can be used with the find_processors function
    
    This function adapts pluggy plugins to be compatible with the traditional find_processors system
    
    :return: A list of (module, processor_name) tuples
    """
    result = []
    
    # For each plugin, create a fake module that can be used with find_processors
    for plugin in plugin_manager.get_plugins():
        try:
            # Get the processor name from this plugin
            name = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            if name:
                processor_name = name[0]
                # For the WHOIS processor specifically, use text_json_diff as the base module
                if processor_name == 'whois':
                    from changedetectionio.processors.text_json_diff import processor as text_json_diff_processor
                    result.append((text_json_diff_processor, processor_name))
        except Exception as e:
            logger.error(f"Error getting processor module from plugin: {str(e)}")
    
    return result