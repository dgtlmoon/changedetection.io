from loguru import logger
from changedetectionio.model import Watch
from .pluggy_interface import plugin_manager
from typing import Dict, Any, List, Tuple, Optional, TypeVar, Type
import functools

# Import and register internal plugins
from . import whois_plugin
from . import test_plugin

# Register plugins
plugin_manager.register(whois_plugin)
plugin_manager.register(test_plugin)

# Load any setuptools entrypoints
plugin_manager.load_setuptools_entrypoints("changedetectionio_processors")

# Type definitions for better type hinting
T = TypeVar('T')
ProcessorClass = TypeVar('ProcessorClass')
ProcessorForm = TypeVar('ProcessorForm')
ProcessorWatchModel = TypeVar('ProcessorWatchModel')
ProcessorInstance = TypeVar('ProcessorInstance')

# Cache for plugin name mapping to improve performance
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
    
    # Return cached map if available
    if _plugin_name_map:
        return _plugin_name_map
    
    # Build the map
    result = {}
    
    # Get all plugins from the plugin manager
    all_plugins = list(plugin_manager.get_plugins())
    
    # First register known internal plugins by name for reliability
    known_plugins = {
        'whois': whois_plugin,
        'test': test_plugin
    }
    
    for name, plugin in known_plugins.items():
        if plugin in all_plugins:
            result[name] = plugin
    
    # Then process remaining plugins through the hook system
    for plugin in all_plugins:
        if plugin in known_plugins.values():
            continue  # Skip plugins we've already registered
            
        try:
            # Get the processor name from this plugin
            name_results = plugin_manager.hook.get_processor_name(plugin=plugin)
            
            if name_results:
                plugin_name = name_results[0]
                
                # Check for name collisions
                if plugin_name in result:
                    logger.warning(f"Plugin name collision: '{plugin_name}' is already registered")
                    continue
                    
                result[plugin_name] = plugin
        except Exception as e:
            logger.error(f"Error getting processor name from plugin: {str(e)}")
    
    # Cache the map
    _plugin_name_map = result
    return result

def _get_plugin_by_name(processor_name: str) -> Optional[Any]:
    """Get a plugin by its processor name
    :param processor_name: Name of the processor
    :return: Plugin object or None
    """
    return _get_plugin_name_map().get(processor_name)

def _call_hook_for_plugin(plugin: Any, hook_name: str, default_value: T = None, **kwargs) -> Optional[T]:
    """Call a hook for a specific plugin and handle exceptions
    :param plugin: The plugin to call the hook for
    :param hook_name: Name of the hook to call
    :param default_value: Default value to return if the hook call fails
    :param kwargs: Additional arguments to pass to the hook
    :return: Result of the hook call or default value
    """
    if not plugin:
        return default_value
    
    try:
        hook = getattr(plugin_manager.hook, hook_name)
        results = hook(plugin=plugin, **kwargs)
        
        if results:
            return results[0]
    except Exception as e:
        logger.error(f"Error calling {hook_name} for plugin: {str(e)}")
    
    return default_value

def get_all_processors() -> List[Tuple[str, str]]:
    """Get all processors
    :return: List of tuples (processor_name, processor_description)
    """
    processors = []
    
    for processor_name, plugin in _get_plugin_name_map().items():
        description = _call_hook_for_plugin(plugin, 'get_processor_description')
        if description:
            processors.append((processor_name, description))
    
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
    plugin = _get_plugin_by_name(processor_name)
    return _call_hook_for_plugin(plugin, 'get_processor_form')

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

    # For each plugin, map to a suitable module for find_processors
    for processor_name, plugin in _get_plugin_name_map().items():
        try:
            processor_class = _call_hook_for_plugin(plugin, 'get_processor_class')
            
            if processor_class:
                # Check if this processor extends the text_json_diff processor
                base_class_name = str(processor_class.__bases__[0].__name__)
                if base_class_name == 'perform_site_check' or 'TextJsonDiffProcessor' in base_class_name:
                    result.append((text_json_diff_processor, processor_name))
        except Exception as e:
            logger.error(f"Error mapping processor module for {processor_name}: {str(e)}")
    
    return result