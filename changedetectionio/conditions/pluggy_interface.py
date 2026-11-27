"""Deprecated: conditions plugins now use the main plugin manager.

The conditions hooks (register_operators, register_operator_choices, register_field_choices,
add_data) are declared on ChangeDetectionSpec in changedetectionio/pluggy_interface.py.
New plugins should use `from changedetectionio.plugin_api import hookimpl`.

This module stays so existing plugins keep working: implementations marked with the old
HookimplMarker("changedetectionio_conditions") are still picked up by the main manager, and the
old "changedetectionio_conditions" entry-point group is still loaded.
"""
import pluggy

from changedetectionio.pluggy_interface import LEGACY_CONDITIONS_NAMESPACE, plugin_manager  # noqa: F401

PLUGIN_NAMESPACE = LEGACY_CONDITIONS_NAMESPACE

hookimpl = pluggy.HookimplMarker(PLUGIN_NAMESPACE)
