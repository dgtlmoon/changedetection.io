"""The public API for changedetection.io plugins.

Plugins should import only from this module. Everything else in the changedetectionio package
is internal and may change between releases without notice; names exported here follow the
deprecation policy in PLUGIN_ROADMAP.md (deprecated names keep working, with a logged warning,
for at least two minor releases).

    from changedetectionio.plugin_api import hookimpl

    @hookimpl
    def ui_edit_stats_extras(watch):
        return "<p>Hello from my plugin</p>"

Register the module under the "changedetectionio" entry-point group in your package's
pyproject.toml so it's discovered at startup:

    [project.entry-points.changedetectionio]
    my_plugin = "my_package.plugin"

The available hooks and their arguments are documented on ChangeDetectionSpec in
changedetectionio/pluggy_interface.py.

Keep plugin modules cheap to import: they're loaded at startup in every instance, so import
heavy dependencies inside your hook functions instead of at the top of the module.

A plugin that raises is logged and counted, and the hook carries on with the other plugins,
so one broken plugin can't stop checks from running.
"""
import inspect

from changedetectionio.pluggy_interface import hookimpl

# Version of this public API, not of changedetection.io. Below 1.0 it can still change between
# minor versions; from 1.0 on, breaking changes mean a major version bump.
PLUGIN_API_VERSION = "0.1.0"


async def await_me_maybe(value):
    """Return `value`, awaiting it first if it's awaitable.

    Hook implementations may be plain functions or `async def` coroutines, so core code that
    calls an async-capable hook passes each result through this helper.
    """
    if inspect.isawaitable(value):
        return await value
    return value


async def gather_hook_results(results):
    """Await every awaitable in a list of hook results, in order, and drop the None results."""
    resolved = []
    for result in results or []:
        result = await await_me_maybe(result)
        if result is not None:
            resolved.append(result)
    return resolved


__all__ = [
    'PLUGIN_API_VERSION',
    'await_me_maybe',
    'gather_hook_results',
    'hookimpl',
]
