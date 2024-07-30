import pluggy
from .hookspecs import HookSpec
import importlib.metadata

# Define the plugin namespace
plugin_namespace = "changedetectionio.restock_price_scraper"

# Create a pluggy.PluginManager instance
pm = pluggy.PluginManager(plugin_namespace)

# Register the hook specifications
pm.add_hookspecs(HookSpec)

# Automatically discover and register plugins using entry points
for entry_point in importlib.metadata.entry_points().get(plugin_namespace, []):
    plugin = entry_point.load()
    pm.register(plugin())
