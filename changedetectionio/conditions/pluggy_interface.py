import pluggy

# Define `pluggy` hookspecs (Specifications for Plugins)
hookspec = pluggy.HookspecMarker("conditions")
hookimpl = pluggy.HookimplMarker("conditions")


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


# ✅ Set up `pluggy` Plugin Manager
plugin_manager = pluggy.PluginManager("conditions")
plugin_manager.add_hookspecs(ConditionsSpec)

# Discover installed plugins
plugin_manager.load_setuptools_entrypoints("conditions")