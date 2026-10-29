#!/usr/bin/env python3
"""Plugin API foundations: failure isolation, async hook results, and the merged conditions hooks."""
import asyncio
import time

import pluggy
import pytest

from changedetectionio import pluggy_interface
from changedetectionio.plugin_api import PLUGIN_API_VERSION, await_me_maybe, gather_hook_results, hookimpl
from changedetectionio.pluggy_interface import (
    collect_ui_edit_stats_extras,
    get_itemprop_availability_from_plugin,
    get_plugin_health,
    plugin_manager,
    apply_update_handler_alter,
)


@pytest.fixture
def register_plugin():
    """Register plugins for one test and always unregister them afterwards."""
    added = []

    def register(plugin, name):
        plugin_manager.register(plugin, name=name)
        added.append(name)
        return plugin

    yield register
    for name in added:
        if plugin_manager.get_plugin(name) is not None:
            plugin_manager.unregister(name=name)


@pytest.fixture
def watch(live_server):
    datastore = live_server.app.config['DATASTORE']
    # Paused, these tests only need the watch object, not a check
    uuid = datastore.add_watch(url='https://example.com/plugin-api-test', extras={'paused': True})
    return datastore.data['watching'][uuid]


def test_plugin_api_exports():
    assert PLUGIN_API_VERSION
    # The public marker is the same one core uses, so either import path registers hooks
    assert hookimpl is pluggy_interface.hookimpl
    assert hookimpl.project_name == pluggy_interface.PLUGIN_NAMESPACE

    # What a processor plugin needs, exported lazily so they're the very same objects as core's
    from changedetectionio import plugin_api
    from changedetectionio.processors.base import difference_detection_processor
    from changedetectionio.processors import get_resolved_processor_config
    from changedetectionio.html_tools import html_to_text
    assert plugin_api.difference_detection_processor is difference_detection_processor
    assert plugin_api.get_resolved_processor_config is get_resolved_processor_config
    assert plugin_api.html_to_text is html_to_text
    assert set(plugin_api.__all__) >= {'difference_detection_processor', 'get_resolved_processor_config', 'html_to_text'}
    with pytest.raises(AttributeError):
        plugin_api.no_such_export


def test_plugin_api_import_stays_cheap():
    """Plugins import plugin_api at startup in every instance, it must not drag in the processor base
    class, the fetchers or lxml until a lazy export is actually used."""
    import subprocess
    import sys
    code = ("import sys, changedetectionio.plugin_api; "
            "print(','.join(m for m in ('changedetectionio.processors.base', 'changedetectionio.html_tools') if m in sys.modules))")
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == '', f"Importing plugin_api eagerly imported: {out}"


def test_raising_plugin_does_not_break_the_hook(register_plugin, watch):
    class Broken:
        @hookimpl
        def ui_edit_stats_extras(self, watch):
            raise RuntimeError("boom from a broken plugin")

    class Working:
        @hookimpl
        def ui_edit_stats_extras(self, watch):
            return '<p id="working-plugin">still here</p>'

    register_plugin(Working(), 'test_isolation_working')
    register_plugin(Broken(), 'test_isolation_broken')

    html = collect_ui_edit_stats_extras(watch)
    assert 'working-plugin' in html, "The other plugins' output must survive one plugin raising"

    health = get_plugin_health('test_isolation_broken')
    assert health['total_failures'] == 1
    assert health['consecutive_failures'] == 1
    assert health['last_hook'] == 'ui_edit_stats_extras'
    assert 'boom from a broken plugin' in health['last_error']
    assert health['errored'] is False
    assert get_plugin_health('test_isolation_working') is None, "A plugin that never failed isn't listed"


def test_plugin_reported_errored_after_consecutive_failures_and_recovers(register_plugin, watch, monkeypatch):
    monkeypatch.setattr(pluggy_interface, 'PLUGIN_CONSECUTIVE_FAILURES_ERRORED', 3)
    state = {'fail': True}

    class Flaky:
        @hookimpl
        def ui_edit_stats_extras(self, watch):
            if state['fail']:
                raise ValueError("flaky")
            return 'ok'

    register_plugin(Flaky(), 'test_isolation_flaky')

    for _ in range(3):
        collect_ui_edit_stats_extras(watch)
    assert get_plugin_health('test_isolation_flaky')['errored'] is True

    state['fail'] = False
    collect_ui_edit_stats_extras(watch)
    health = get_plugin_health('test_isolation_flaky')
    assert health['consecutive_failures'] == 0
    assert health['total_failures'] == 3
    assert health['errored'] is False


def test_firstresult_hook_falls_through_a_raising_plugin(register_plugin):
    class Answers:
        @hookimpl
        def get_itemprop_availability_override(self, content):
            return {'price': 9.99, 'currency': 'USD', 'availability': 'instock'}

    class Raises:
        @hookimpl(tryfirst=True)
        def get_itemprop_availability_override(self, content):
            raise RuntimeError("restock plugin exploded")

    register_plugin(Answers(), 'test_isolation_restock_answers')
    register_plugin(Raises(), 'test_isolation_restock_raises')

    result = get_itemprop_availability_from_plugin('<html>x</html>', 'html_requests', None, 'https://example.com')
    assert result['price'] == 9.99
    assert get_plugin_health('test_isolation_restock_raises')['total_failures'] == 1


def test_update_handler_alter_raising_keeps_original_handler(register_plugin):
    class Raises:
        @hookimpl
        def update_handler_alter(self, update_handler, watch, datastore):
            raise RuntimeError("wrapper failed")

    register_plugin(Raises(), 'test_isolation_handler_alter')
    original = object()
    assert apply_update_handler_alter(original, {'uuid': 'x'}, None) is original


def test_async_hook_results_are_awaited_and_isolated(register_plugin, watch, monkeypatch):
    monkeypatch.setattr(pluggy_interface, 'PLUGIN_ASYNC_HOOK_TIMEOUT', 0.5)

    class AsyncGood:
        @hookimpl
        async def ui_edit_stats_extras(self, watch):
            await asyncio.sleep(0)
            return 'async-good'

    class AsyncBroken:
        @hookimpl
        async def ui_edit_stats_extras(self, watch):
            raise RuntimeError("async boom")

    class AsyncHung:
        @hookimpl
        async def ui_edit_stats_extras(self, watch):
            await asyncio.sleep(30)
            return 'never'

    register_plugin(AsyncGood(), 'test_async_good')
    register_plugin(AsyncBroken(), 'test_async_broken')
    register_plugin(AsyncHung(), 'test_async_hung')

    raw = plugin_manager.hook.ui_edit_stats_extras(watch=watch)
    started = time.time()
    results = asyncio.run(gather_hook_results(raw))
    assert time.time() - started < 5, "A hung async plugin must be cut off by the timeout"

    assert 'async-good' in results
    assert 'never' not in results
    assert get_plugin_health('test_async_broken')['total_failures'] == 1
    assert 'TimeoutError' in get_plugin_health('test_async_hung')['last_error']


def test_await_me_maybe_passes_plain_values_through():
    async def coro():
        return 'awaited'

    assert asyncio.run(await_me_maybe('plain')) == 'plain'
    assert asyncio.run(await_me_maybe(coro())) == 'awaited'
    # Classes are callable but must not be called, register_* hooks return classes
    assert asyncio.run(await_me_maybe(dict)) is dict


def test_hooks_that_propagate_exceptions_still_raise(register_plugin, monkeypatch):
    # The decision is taken when the plugin is registered, so patch before registering
    monkeypatch.setattr(pluggy_interface, 'HOOKS_THAT_PROPAGATE_EXCEPTIONS', {'get_html_head_extras'})

    class Raises:
        @hookimpl
        def get_html_head_extras(self):
            raise ValueError("meant to reach the caller")

    register_plugin(Raises(), 'test_propagates')
    with pytest.raises(ValueError, match="meant to reach the caller"):
        plugin_manager.hook.get_html_head_extras()
    assert get_plugin_health('test_propagates')['total_failures'] == 1, "Still logged and counted"


def test_conditions_hooks_live_on_the_main_manager():
    from changedetectionio.conditions import get_custom_operations, get_field_choices, get_operator_choices

    field_names = [name for name, _ in get_field_choices()]
    # Built-in conditions plugin first, then the bundled plugins
    assert field_names[:3] == [None, 'extracted_number', 'page_filtered_text']
    assert 'levenshtein_ratio' in field_names and 'word_count' in field_names

    assert 'starts_with' in [name for name, _ in get_operator_choices()]
    assert 'starts_with' in get_custom_operations()
    assert '==' in get_custom_operations(), "json_logic builtins are still included"


def test_legacy_conditions_marker_still_works(register_plugin):
    from changedetectionio.conditions import get_field_choices
    from changedetectionio.conditions.form import ConditionFormRow
    # The old import path keeps working for published plugins
    from changedetectionio.conditions.pluggy_interface import hookimpl as legacy_import_hookimpl

    legacy_marker = pluggy.HookimplMarker("changedetectionio_conditions")

    class OldStylePlugin:
        @legacy_marker
        def register_field_choices(self):
            return [('legacy_field', 'Legacy field')]

    class OldImportPathPlugin:
        @legacy_import_hookimpl
        def register_field_choices(self):
            return [('legacy_import_field', 'Legacy import field')]

    register_plugin(OldStylePlugin(), 'test_legacy_conditions_marker')
    register_plugin(OldImportPathPlugin(), 'test_legacy_conditions_import')

    field_names = [name for name, _ in get_field_choices()]
    assert 'legacy_field' in field_names
    assert 'legacy_import_field' in field_names

    # Forms collect choices when they're built, so a plugin registered after startup shows up
    form_field_names = [name for name, _ in ConditionFormRow().field.choices]
    assert 'legacy_field' in form_field_names


def test_conditions_add_data_survives_broken_and_slow_plugins(register_plugin, monkeypatch):
    import changedetectionio.conditions as conditions
    monkeypatch.setattr(conditions, 'ADD_DATA_TIMEOUT', 0.5)

    class Broken:
        @hookimpl
        def add_data(self, current_watch_uuid, application_datastruct, ephemeral_data):
            raise RuntimeError("add_data boom")

    class Slow:
        @hookimpl
        def add_data(self, ephemeral_data):
            time.sleep(3)
            return {'slow_fact': 1}

    class Good:
        @hookimpl
        def add_data(self, ephemeral_data):
            # Declares only the argument it needs, like pluggy allows
            return {'good_fact': len(ephemeral_data.get('text', ''))}

    register_plugin(Broken(), 'test_add_data_broken')
    register_plugin(Slow(), 'test_add_data_slow')
    register_plugin(Good(), 'test_add_data_good')

    application_datastruct = {'watching': {'w1': {
        'conditions': [{'field': 'good_fact', 'operator': '==', 'value': '5'}],
        'conditions_match_logic': 'ALL',
    }}}

    started = time.time()
    outcome = conditions.execute_ruleset_against_all_plugins('w1', application_datastruct, {'text': 'hello'})
    assert time.time() - started < 2.5, "The slow plugin must be skipped, not waited for"
    assert outcome['executed_data']['good_fact'] == 5
    assert 'slow_fact' not in outcome['executed_data']
    assert outcome['result'] is True
    assert get_plugin_health('test_add_data_broken')['total_failures'] == 1
