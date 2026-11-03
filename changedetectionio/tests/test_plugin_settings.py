#!/usr/bin/env python3
"""Plugin settings on the watch, group and system settings pages, resolved watch -> group -> system,
plus plugin state, the engine override and watch-list notes. See changedetectionio/plugin_settings.py."""
import pytest
from flask import url_for
from wtforms import Form, RadioField, StringField, validators

from changedetectionio.plugin_api import (SettingsSection, clear_plugin_state, get_plugin_state, hookimpl,
                                          resolved_plugin_settings, set_plugin_state)
from changedetectionio.pluggy_interface import plugin_manager

PLUGIN_ID = 'test_settings'


def _form(scope):
    choices = [('off', 'Off'), ('on', 'On')]
    if scope != 'global':
        choices.insert(0, ('', 'Inherit'))
    attrs = {'mode': RadioField('Mode', choices=choices, default='' if scope != 'global' else 'off',
                                validators=[validators.Optional()])}
    if scope == 'global':
        attrs['note'] = StringField('Note', validators=[validators.Optional(), validators.Length(max=20)])
    return type(f'TestSettings{scope}', (Form,), attrs)


class SettingsPlugin:
    def __init__(self):
        self.override_to = None

    @hookimpl
    def settings_form_section(self, scope):
        return SettingsSection(plugin_id=PLUGIN_ID, label=f'Test settings {scope}', form_class=_form(scope))

    @hookimpl
    def fetch_engine_override(self, watch, engine):
        if resolved_plugin_settings(watch, PLUGIN_ID).get('mode') == 'on':
            return self.override_to
        return None

    @hookimpl
    def watch_list_extra_text(self, watch):
        if get_plugin_state(watch, PLUGIN_ID).get('flag'):
            return 'Plugin note <b>escaped</b>'
        return None


@pytest.fixture
def settings_plugin():
    plugin = SettingsPlugin()
    plugin_manager.register(plugin, name='test_settings_plugin')
    yield plugin
    plugin_manager.unregister(name='test_settings_plugin')


def _watch(datastore, **extras):
    return datastore.data['watching'][datastore.add_watch(url='https://example.com/x', extras={'paused': True, **extras})]


def test_sections_render_and_save_on_all_three_pages(client, live_server, measure_memory_usage, datastore_path, settings_plugin):
    datastore = client.application.config.get('DATASTORE')

    # System settings, Fetching tab
    res = client.get(url_for("settings.settings_page"))
    fetching = res.data.decode().split('id="fetching"')[1].split('tab-pane-inner')[0]
    assert 'Test settings global' in fetching and 'name="plugin_test_settings-mode"' in fetching
    form = {k: v for k, v in [('application-pager_size', '50'), ('application-fetch_backend', 'html_requests'),
                              ('requests-time_between_check-minutes', '180'), ('application-empty_pages_are_a_change', '')]}
    client.post(url_for("settings.settings_page"),
                data={**form, 'plugin_test_settings-mode': 'on', 'plugin_test_settings-note': 'hello'},
                follow_redirects=True)
    assert datastore.data['settings']['application']['plugin_settings'][PLUGIN_ID] == {'mode': 'on', 'note': 'hello'}
    assert 'plugin_test_settings' not in datastore.data['settings']['application']

    # Group, Browser tab
    tag_uuid = datastore.add_tag(title='Group')
    res = client.get(url_for("tags.form_tag_edit", uuid=tag_uuid))
    browser_tab = res.data.decode().split('id="browser"')[1].split('tab-pane-inner')[0]
    assert 'Test settings tag' in browser_tab
    client.post(url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
                data={'title': 'Group', 'plugin_test_settings-mode': 'off'}, follow_redirects=True)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    assert tag['plugin_settings'][PLUGIN_ID] == {'mode': 'off'}
    assert 'plugin_test_settings' not in tag

    # Watch, Request tab
    watch = _watch(datastore)
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch['uuid']))
    request_tab = res.data.decode().split('id="request"')[1].split('tab-pane-inner')[0]
    assert 'Test settings watch' in request_tab
    client.post(url_for("ui.ui_edit.edit_page", uuid=watch['uuid']),
                data={'url': 'https://example.com/x', 'fetch_backend': 'html_requests', 'time_between_check_use_default': 'y',
                      'plugin_test_settings-mode': 'on'}, follow_redirects=True)
    watch = datastore.data['watching'][watch['uuid']]
    assert watch['plugin_settings'][PLUGIN_ID] == {'mode': 'on'}
    assert 'plugin_test_settings' not in watch
    # Reloads into the form
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch['uuid']))
    import re
    assert re.search(rb'<input checked id="plugin_test_settings-mode-\d" name="plugin_test_settings-mode" type="radio" value="on">', res.data)


def test_resolution_watch_then_group_then_system(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['plugin_settings'] = {PLUGIN_ID: {'mode': 'off', 'note': 'system'}}
    watch = _watch(datastore)
    assert resolved_plugin_settings(watch, PLUGIN_ID) == {'mode': 'off', 'note': 'system'}

    tag_uuid = datastore.add_tag(title='G')
    datastore.data['settings']['application']['tags'][tag_uuid]['plugin_settings'] = {PLUGIN_ID: {'mode': 'on'}}
    watch['tags'] = [tag_uuid]
    assert resolved_plugin_settings(watch, PLUGIN_ID) == {'mode': 'on', 'note': 'system'}, "field by field"

    watch['plugin_settings'] = {PLUGIN_ID: {'mode': ''}}
    assert resolved_plugin_settings(watch, PLUGIN_ID)['mode'] == 'on', "'' means inherit"
    watch['plugin_settings'] = {PLUGIN_ID: {'mode': 'off'}}
    assert resolved_plugin_settings(watch, PLUGIN_ID)['mode'] == 'off', "the watch's own value wins"


def test_plugin_state_engine_override_and_watch_list_note(client, live_server, measure_memory_usage, datastore_path, settings_plugin):
    datastore = client.application.config.get('DATASTORE')
    watch = _watch(datastore, fetch_backend='html_requests')

    set_plugin_state(watch, PLUGIN_ID, flag=True)
    assert get_plugin_state(watch, PLUGIN_ID) == {'flag': True}
    res = client.get(url_for("watchlist.index"))
    assert b'<div class="extra-watch-text">Plugin note &lt;b&gt;escaped&lt;/b&gt;</div>' in res.data
    clear_plugin_state(watch, PLUGIN_ID)
    assert get_plugin_state(watch, PLUGIN_ID) == {}
    assert b'extra-watch-text' not in client.get(url_for("watchlist.index")).data

    # The override changes both what fetches and what the edit page offers
    from changedetectionio.content_fetchers import resolve_content_fetcher
    watch['plugin_settings'] = {PLUGIN_ID: {'mode': 'on'}}
    settings_plugin.override_to = 'html_playwright_builtin'
    assert watch.resolved_fetch_engine == 'html_playwright_builtin'
    _cls, backend, _url, _cfg = resolve_content_fetcher(watch, datastore)
    assert backend == 'html_playwright_builtin'
    assert b'id="visualselector-tab"' in client.get(url_for("ui.ui_edit.edit_page", uuid=watch['uuid'])).data

    settings_plugin.override_to = 'no_such_engine'
    assert watch.resolved_fetch_engine == 'html_requests', "an unknown engine is ignored"


def test_hidden_engines_stay_usable(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.playwright_builtin import fetcher as builtin
    monkeypatch.setattr(builtin, 'offered_as_browser', False)
    assert 'html_playwright_builtin' not in dict(content_fetchers.available_fetchers())
    assert getattr(content_fetchers, 'html_playwright_builtin') is builtin


def test_plugin_state_written_through_a_copy_reaches_the_stored_watch(client, live_server, measure_memory_usage, datastore_path):
    """A check works on a deepcopy of the watch; state a plugin sets on it must not be lost."""
    from copy import deepcopy
    datastore = client.application.config.get('DATASTORE')
    stored = _watch(datastore)
    copy = deepcopy(stored)
    set_plugin_state(copy, PLUGIN_ID, flag=True)
    assert get_plugin_state(datastore.data['watching'][stored['uuid']], PLUGIN_ID) == {'flag': True}
    assert get_plugin_state(copy, PLUGIN_ID) == {'flag': True}
    clear_plugin_state(deepcopy(stored), PLUGIN_ID)
    assert get_plugin_state(datastore.data['watching'][stored['uuid']], PLUGIN_ID) == {}


def test_plugin_rechecks_are_rate_limited(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.plugin_settings import queue_recheck
    datastore = client.application.config.get('DATASTORE')
    uuid = _watch(datastore)['uuid']
    assert queue_recheck(uuid) is True
    assert queue_recheck(uuid) is False, "a second request within a minute is refused"
