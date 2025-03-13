import pluggy
from . import default_plugin  # Import the default plugin

# ✅ Ensure that the namespace in HookspecMarker matches PluginManager
PLUGIN_NAMESPACE = "conditions"

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

# ✅ Set up Pluggy Plugin Manager
plugin_manager = pluggy.PluginManager(PLUGIN_NAMESPACE)

# ✅ Register hookspecs (Ensures they are detected)
plugin_manager.add_hookspecs(ConditionsSpec)

# ✅ Register built-in plugins manually
plugin_manager.register(default_plugin, "default_plugin")

# ✅ Discover installed plugins from external packages (if any)
plugin_manager.load_setuptools_entrypoints(PLUGIN_NAMESPACE)
