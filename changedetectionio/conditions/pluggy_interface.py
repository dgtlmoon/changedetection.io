import pluggy
import os
import importlib
import sys
from . import default_plugin

# ✅ Ensure that the namespace in HookspecMarker matches PluginManager
PLUGIN_NAMESPACE = "changedetectionio_conditions"

hookspec = pluggy.HookspecMarker(PLUGIN_NAMESPACE)
hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)


class ConditionsSpec:
    """Hook specifications for extending JSON Logic conditions."""

    @hookspec
    def register_operators():
        """Return a dictionary of new JSON Logic operators."""
        pass

    @hookspec
    def register_operator_choices():
        """Return a list of new operator choices."""
        pass

    @hookspec
    def register_field_choices():
        """Return a list of new field choices."""
        pass

    @hookspec
    def add_data(current_watch_uuid, application_datastruct, ephemeral_data):
        """Add to the datadict"""
        pass
        
    @hookspec
    def ui_edit_stats_extras(watch):
        """Return HTML content to add to the stats tab in the edit view"""
        pass

# ✅ Set up Pluggy Plugin Manager
plugin_manager = pluggy.PluginManager(PLUGIN_NAMESPACE)

# ✅ Register hookspecs (Ensures they are detected)
plugin_manager.add_hookspecs(ConditionsSpec)

# ✅ Register built-in plugins manually
plugin_manager.register(default_plugin, "default_plugin")

# ✅ Load plugins from the plugins directory
def load_plugins_from_directory():
    plugins_dir = os.path.join(os.path.dirname(__file__), 'plugins')
    if not os.path.exists(plugins_dir):
        return
        
    # Get all Python files (excluding __init__.py)
    for filename in os.listdir(plugins_dir):
        if filename.endswith(".py") and filename != "__init__.py":
            module_name = filename[:-3]  # Remove .py extension
            module_path = f"changedetectionio.conditions.plugins.{module_name}"
            
            try:
                module = importlib.import_module(module_path)
                # Register the plugin with pluggy
                plugin_manager.register(module, module_name)
            except (ImportError, AttributeError) as e:
                print(f"Error loading plugin {module_name}: {e}")

# Load plugins from the plugins directory
load_plugins_from_directory()

# ✅ Discover installed plugins from external packages (if any)
plugin_manager.load_setuptools_entrypoints(PLUGIN_NAMESPACE)
