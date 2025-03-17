from loguru import logger
from changedetectionio.model import Watch
from .pluggy_interface import plugin_manager
from typing import Dict, Any, List, Tuple, Optional, TypeVar, Type
import functools

# Clear global cache to ensure clean state
_plugin_name_map = {}

# Import both plugins first to avoid registration order issues
from . import whois_plugin
from . import test_plugin

# Now register them after all imports
plugin_manager.register(whois_plugin)
logger.debug("Registered whois_plugin")
plugin_manager.register(test_plugin)
logger.debug("Registered test_plugin")

# Log the plugins list after registration
all_plugins = plugin_manager.get_plugins()
logger.debug(f"Plugin manager has {len(all_plugins)} plugins after registration")

# Load any setuptools entrypoints
plugin_manager.load_setuptools_entrypoints("changedetectionio_processors")

# Type definitions for better type hinting
T = TypeVar('T')
ProcessorClass = TypeVar('ProcessorClass')
ProcessorForm = TypeVar('ProcessorForm')
ProcessorWatchModel = TypeVar('ProcessorWatchModel')
ProcessorInstance = TypeVar('ProcessorInstance')

# Cache for plugin name mapping to improve performance
# This will be populated after the first call to _get_plugin_name_map
_plugin_name_map: Dict[str, Any] = {}

def register_plugin(plugin_module):
    """Register a processor plugin"""
    plugin_manager.register(plugin_module)
    # Clear the plugin name map cache when a new plugin is registered
    global _plugin_name_map
    _plugin_name_map = {}

def _get_plugin_name_map() -> Dict[str, Any]:
    """Get a mapping of processor names to plugins
    :return: Dictionary mapping processor names to plugins
    """
    global _plugin_name_map
    
    # Return cached map if available - but only if it's not empty
    if _plugin_name_map and len(_plugin_name_map) > 0:
        logger.debug(f"Using cached plugin map: {list(_plugin_name_map.keys())}")
        return _plugin_name_map
    
    # Build the map
    result = {}
    
    # Get all plugins from the plugin manager
    all_plugins = list(plugin_manager.get_plugins())
    logger.debug(f"Processing {len(all_plugins)} plugins from plugin manager: {all_plugins}")
    
    # First, directly check for known plugins to ensure they're included
    # This is a backup strategy in case the hook mechanism fails
    known_plugins = {
        'whois': whois_plugin,
        'test': test_plugin
    }
    
    for name, plugin in known_plugins.items():
        if plugin in all_plugins:
            logger.debug(f"Found known plugin '{name}' in plugin list")
            result[name] = plugin
    
    # Now process all plugins through the hook system
    for plugin in all_plugins:
        try:
            # For debugging, log the plugin's module name
            module_name = getattr(plugin, '__name__', str(plugin))
            logger.debug(f"Processing plugin: {module_name}")
            
            # Call get_processor_name individually for each plugin
            try:
                # Use a direct attribute call if it exists (more reliable)
                if hasattr(plugin, 'get_processor_name'):
                    plugin_name = plugin.get_processor_name()
                    logger.debug(f"Direct call to get_processor_name returned: {plugin_name}")
                else:
                    # Fall back to the hook system
                    name_results = plugin_manager.hook.get_processor_name(plugin=plugin)
                    if name_results:
                        plugin_name = name_results[0]
                        logger.debug(f"Hook call to get_processor_name returned: {plugin_name}")
                    else:
                        logger.error(f"Plugin {module_name} did not return a name via hook")
                        continue
                
                # Add to result if we got a name
                if plugin_name:
                    # Check for collisions
                    if plugin_name in result and result[plugin_name] != plugin:
                        logger.warning(f"Plugin name collision: '{plugin_name}' is already registered. "
                                      f"The latest registration will overwrite the previous one.")
                    
                    result[plugin_name] = plugin
                    logger.debug(f"Successfully registered processor plugin: '{plugin_name}'")
            except Exception as e:
                logger.error(f"Error getting name for plugin {module_name}: {str(e)}")
                
        except Exception as e:
            import traceback
            logger.error(f"Error processing plugin: {str(e)}")
            logger.error(traceback.format_exc())
    
    # Verify we have all the required plugins
    if 'whois' not in result:
        logger.error("Critical error: whois plugin is missing from the plugin map!")
        # Try to manually add it if it's in the all_plugins list
        if whois_plugin in all_plugins:
            logger.warning("Manually adding whois_plugin to map")
            result['whois'] = whois_plugin
    
    if 'test' not in result:
        logger.error("Critical error: test plugin is missing from the plugin map!")
        # Try to manually add it if it's in the all_plugins list
        if test_plugin in all_plugins:
            logger.warning("Manually adding test_plugin to map")
            result['test'] = test_plugin
    
    # Log all registered plugins for debugging
    logger.debug(f"Registered plugins ({len(result)} total): {list(result.keys())}")
    
    # Cache the map only if we have at least all the expected plugins
    if len(result) >= 2:
        _plugin_name_map = result
    else:
        logger.error(f"Not caching plugin map - expected at least 2 plugins but found {len(result)}")
    
    return result

def _get_plugin_by_name(processor_name: str) -> Optional[Any]:
    """Get a plugin by its processor name
    :param processor_name: Name of the processor
    :return: Plugin object or None
    """
    plugin_map = _get_plugin_name_map()
    plugin = plugin_map.get(processor_name)
    
    if plugin is None:
        logger.error(f"Plugin not found: '{processor_name}'. Available plugins: {list(plugin_map.keys())}")
    
    return plugin

def _call_hook_for_plugin(plugin: Any, hook_name: str, default_value: T = None, **kwargs) -> Optional[T]:
    """Call a hook for a specific plugin and handle exceptions
    :param plugin: The plugin to call the hook for
    :param hook_name: Name of the hook to call
    :param default_value: Default value to return if the hook call fails
    :param kwargs: Additional arguments to pass to the hook
    :return: Result of the hook call or default value
    """
    if not plugin:
        logger.debug(f"Cannot call hook {hook_name}: plugin is None")
        return default_value
    
    try:
        # Ensure the hook exists
        if not hasattr(plugin_manager.hook, hook_name):
            logger.error(f"Hook {hook_name} does not exist in the plugin manager")
            return default_value
        
        hook = getattr(plugin_manager.hook, hook_name)
        logger.debug(f"Calling hook {hook_name} for plugin {plugin}")
        
        # Call the hook with the plugin
        results = hook(plugin=plugin, **kwargs)
        
        if not results:
            logger.debug(f"Hook {hook_name} returned no results")
            return default_value
        
        logger.debug(f"Hook {hook_name} returned {len(results)} results: {results}")
        return results[0]
    except Exception as e:
        logger.error(f"Error calling {hook_name} for plugin: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
    
    return default_value

def get_all_processors() -> List[Tuple[str, str]]:
    """Get all processors
    :return: List of tuples (processor_name, processor_description)
    """
    processors = []
    
    # Get the plugin map
    plugin_map = _get_plugin_name_map()
    logger.debug(f"Getting descriptions for processors: {list(plugin_map.keys())}")
    
    # Process each plugin
    for processor_name, plugin in plugin_map.items():
        try:
            # Try direct attribute access first (more reliable)
            if hasattr(plugin, 'get_processor_description'):
                try:
                    description = plugin.get_processor_description()
                    logger.debug(f"Got description for {processor_name} via direct call: {description}")
                except Exception as e:
                    logger.error(f"Error calling get_processor_description directly on {processor_name}: {str(e)}")
                    description = None
            else:
                # Fall back to hook system
                description = _call_hook_for_plugin(plugin, 'get_processor_description')
                logger.debug(f"Got description for {processor_name} via hook: {description}")
            
            # Check if both name and description were returned
            if description:
                processors.append((processor_name, description))
                logger.debug(f"Added processor {processor_name} with description: {description}")
            else:
                logger.error(f"No description found for processor {processor_name}")
        except Exception as e:
            import traceback
            logger.error(f"Error getting processor info for {processor_name}: {str(e)}")
            logger.error(traceback.format_exc())
    
    logger.debug(f"Returning {len(processors)} processors: {processors}")
    return processors

def get_processor_class(processor_name: str) -> Optional[Type[ProcessorClass]]:
    """Get processor class by name
    :param processor_name: Name of the processor
    :return: Processor class or None
    """
    plugin = _get_plugin_by_name(processor_name)
    return _call_hook_for_plugin(plugin, 'get_processor_class')

def get_processor_form(processor_name: str) -> Optional[Type[ProcessorForm]]:
    """Get processor form by name
    :param processor_name: Name of the processor
    :return: Processor form class or None
    """
    # Force clear the plugin cache to ensure we have fresh data
    global _plugin_name_map
    _plugin_name_map = {}
    
    plugin = _get_plugin_by_name(processor_name)
    
    if plugin is None:
        logger.error(f"Cannot get form for processor '{processor_name}': plugin not found")
        return None
    
    form = _call_hook_for_plugin(plugin, 'get_processor_form')
    
    if form is None:
        logger.error(f"Form class not found for processor '{processor_name}'")
    
    return form

def get_processor_watch_model(processor_name: str) -> Type[ProcessorWatchModel]:
    """Get processor watch model by name
    :param processor_name: Name of the processor
    :return: Watch model class or default Watch model
    """
    plugin = _get_plugin_by_name(processor_name)
    return _call_hook_for_plugin(plugin, 'get_processor_watch_model', default_value=Watch.model)

def get_processor_site_check(processor_name: str, datastore: Any, watch_uuid: str) -> Optional[ProcessorInstance]:
    """Get a processor instance ready to perform site check
    :param processor_name: Name of the processor
    :param datastore: The application datastore
    :param watch_uuid: The UUID of the watch to check
    :return: A processor instance ready to perform site check, or None
    """
    plugin = _get_plugin_by_name(processor_name)
    if not plugin:
        return None
    
    # Try to get the perform_site_check implementation
    try:
        processor = _call_hook_for_plugin(
            plugin, 
            'perform_site_check', 
            datastore=datastore, 
            watch_uuid=watch_uuid
        )
        if processor:
            return processor
        
        # If no perform_site_check hook implementation, try getting the class and instantiating it
        processor_class = _call_hook_for_plugin(plugin, 'get_processor_class')
        if processor_class:
            return processor_class(datastore=datastore, watch_uuid=watch_uuid)
    except Exception as e:
        logger.error(f"Error getting processor site check for {processor_name}: {str(e)}")
    
    return None

def get_display_link(url: str, processor_name: str) -> Optional[str]:
    """Get a custom display link for the given processor
    :param url: The original URL from the watch
    :param processor_name: Name of the processor
    :return: A string with the custom display link or None to use the default
    """
    plugin = _get_plugin_by_name(processor_name)
    return _call_hook_for_plugin(
        plugin, 
        'get_display_link', 
        url=url, 
        processor_name=processor_name
    )

def get_plugin_processor_modules() -> List[Tuple[Any, str]]:
    """Get processor modules for all plugins that can be used with the find_processors function
    
    This function adapts pluggy plugins to be compatible with the traditional find_processors system
    
    :return: A list of (module, processor_name) tuples
    """
    result = []
    
    # Import base modules once to avoid repeated imports
    from changedetectionio.processors.text_json_diff import processor as text_json_diff_processor
    
    # For each plugin, create a fake module that can be used with find_processors
    for processor_name, plugin in _get_plugin_name_map().items():
        try:
            # Get the processor class for this plugin
            processor_class = _call_hook_for_plugin(plugin, 'get_processor_class')
            
            if processor_class:
                # Check if this processor inherits from TextJsonDiffProcessor
                from changedetectionio.processors.text_json_diff.processor import TextJsonDiffProcessor
                if issubclass(processor_class, TextJsonDiffProcessor) or 'TextJsonDiffProcessor' in str(processor_class.__bases__):
                    result.append((text_json_diff_processor, processor_name))
                else:
                    # For non-inherited processors, could create a mapping to their base module
                    # Future enhancement: dynamically determine base module based on inheritance
                    logger.debug(f"Processor {processor_name} does not inherit from TextJsonDiffProcessor")
        except Exception as e:
            logger.error(f"Error determining processor module for {processor_name}: {str(e)}")
    
    return result