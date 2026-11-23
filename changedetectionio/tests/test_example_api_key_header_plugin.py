#!/usr/bin/env python3
"""The api_key_header example plugin (example_plugins/request/api_key_header), and with it the hooks for plugins that
change the request: ui_edit_request_settings (a nested form in the edit page's Request tab, saved to the watch's data
dir), fetch_request_alter (adds the header before the fetch) and watch_settings_files (Clear history keeps the file)."""
import json
import os

import pytest
from flask import url_for

from changedetectionio.plugin_api import hookimpl

from .util import delete_all_watches, import_example_plugin, wait_for_all_checks

PLUGIN_ID = 'cdio_example_api_key_header'
FIELD = f'plugin_settings_{PLUGIN_ID}'


@pytest.fixture
def api_key_header_plugin(live_server):
    from jinja2 import ChoiceLoader, FileSystemLoader

    from changedetectionio.pluggy_interface import plugin_manager

    plugin = import_example_plugin('request/api_key_header', PLUGIN_ID)
    plugin_manager.register(plugin, PLUGIN_ID)
    # What changedetection.io does at startup for every installed plugin with a templates/ dir
    app = live_server.app
    original_loader = app.jinja_loader
    app.jinja_loader = ChoiceLoader([original_loader, FileSystemLoader(os.path.join(os.path.dirname(plugin.__file__), 'templates'))])
    app.jinja_env.cache.clear()
    yield plugin
    app.jinja_loader = original_loader
    app.jinja_env.cache.clear()
    plugin_manager.unregister(plugin)


def _edit(client, uuid, test_url, **plugin_fields):
    data = {
        "url": test_url,
        "tags": "",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y",
        "plugin_request_settings_shown": PLUGIN_ID,
    }
    data.update({f"{FIELD}-{k}": v for k, v in plugin_fields.items()})
    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid), data=data, follow_redirects=True)
    assert b"Updated watch." in res.data
    return res


def test_api_key_header_plugin(client, live_server, measure_memory_usage, datastore_path, api_key_header_plugin):
    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_headers', _external=True)
    uuid = datastore.add_watch(url=test_url)
    watch = datastore.data['watching'][uuid]
    settings_file = os.path.join(watch.data_dir, f'{PLUGIN_ID}.json')

    # The section is on the edit page, in the Request tab's advanced options
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert f'id="plugin-request-settings-{PLUGIN_ID}"'.encode() in res.data
    assert f'name="{FIELD}-api_key"'.encode() in res.data
    assert b'API key (example plugin)' in res.data

    _edit(client, uuid, test_url, header_name='X-Api-Key', api_key='secret-123')

    # Saved to the watch's data dir, not to the watch
    with open(settings_file) as f:
        assert json.load(f) == {'header_name': 'X-Api-Key', 'api_key': 'secret-123'}
    assert FIELD not in datastore.data['watching'][uuid]
    assert 'secret-123' not in json.dumps(dict(datastore.data['watching'][uuid]), default=str)

    # Sent with the check (fetch_request_alter), the test endpoint echoes the request headers back
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)
    assert b'X-Api-Key:secret-123' in res.data

    # The page doesn't show the key again, and an empty field keeps it (the plugin's on_save)
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert b'secret-123' not in res.data
    assert b'value="X-Api-Key"' in res.data
    _edit(client, uuid, test_url, header_name='X-Other-Key', api_key='')
    with open(settings_file) as f:
        assert json.load(f) == {'header_name': 'X-Other-Key', 'api_key': 'secret-123'}

    # A save where the section wasn't on the page (the Request tab isn't shown for every fetcher) leaves it alone
    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid),
                      data={"url": test_url, "tags": "", "fetch_backend": "html_requests", "time_between_check_use_default": "y"},
                      follow_redirects=True)
    assert b"Updated watch." in res.data
    with open(settings_file) as f:
        assert json.load(f)['api_key'] == 'secret-123'

    # "Clear history" keeps it (watch_settings_files)
    datastore.clear_watch_history(uuid)
    assert os.path.isfile(settings_file)

    # The form's validation errors show with the rest of the page, nothing is saved
    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid),
                      data={"url": test_url, "tags": "", "fetch_backend": "html_requests", "time_between_check_use_default": "y",
                            "plugin_request_settings_shown": PLUGIN_ID, f"{FIELD}-header_name": "Bad header!"},
                      follow_redirects=True)
    assert b"Updated watch." not in res.data
    assert b"Letters, digits and - only" in res.data
    with open(settings_file) as f:
        assert json.load(f)['header_name'] == 'X-Other-Key'

    delete_all_watches(client)


class _FailingRequestPlugin:
    """A fetch_request_alter that can't do its job, e.g. the token endpoint is down."""

    @staticmethod
    @hookimpl
    def fetch_request_alter(watch, datastore, request):
        raise RuntimeError("Token endpoint said no")


def test_fetch_request_alter_exception_fails_the_check(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.pluggy_interface import plugin_manager

    plugin = _FailingRequestPlugin()
    plugin_manager.register(plugin, 'test_failing_request_plugin')
    try:
        datastore = client.application.config.get('DATASTORE')
        uuid = datastore.add_watch(url=url_for('test_headers', _external=True))
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        # Not sent without what the plugin meant to add: the check failed with the plugin's message
        assert 'Token endpoint said no' in (datastore.data['watching'][uuid].get('last_error') or '')
        assert not datastore.data['watching'][uuid].history_n
    finally:
        plugin_manager.unregister(plugin)
        delete_all_watches(client)
