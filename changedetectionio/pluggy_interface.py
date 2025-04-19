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