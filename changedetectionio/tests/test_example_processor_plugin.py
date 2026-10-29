#!/usr/bin/env python3
"""The example processor plugin (example_plugins/processor/wordcounter) works end to end through the
same register_processor path a pip-installed plugin uses: created via the API, checked, and its
processor_state_word_counter published on the watch GET and the watch list."""
import json
import os

import pytest
from flask import url_for

from .util import wait_for_all_checks, delete_all_watches


def _clear_processor_and_spec_caches():
    # Processor discovery and the merged API spec are cached at first use, a plugin registered
    # afterwards (like here) is only seen once these are cleared
    from changedetectionio import processors, api
    for f in (processors.find_processors, processors.get_plugin_processor_metadata, processors._available_processors_cached,
              api.build_merged_spec_dict, api.get_openapi_spec, api.get_openapi_schema_dict,
              api._resolve_schema_properties, api.get_watch_schema_properties, api.get_tag_schema_properties):
        f.cache_clear()


@pytest.fixture
def wordcounter_plugin():
    """What `pip install .` + the entry point would do: import cdio_example_wordcounter as its own
    top-level package and register it."""
    import importlib
    import sys
    from changedetectionio.pluggy_interface import plugin_manager

    example_dir = os.path.join(os.path.dirname(__file__), '..', 'example_plugins', 'processor', 'wordcounter')
    sys.path.insert(0, os.path.abspath(example_dir))
    try:
        wordcounter = importlib.import_module('cdio_example_wordcounter')
    finally:
        sys.path.pop(0)

    plugin_manager.register(wordcounter, 'cdio_example_wordcounter')
    _clear_processor_and_spec_caches()
    yield wordcounter
    plugin_manager.unregister(wordcounter)
    _clear_processor_and_spec_caches()


def test_example_wordcounter_processor_plugin(client, live_server, measure_memory_usage, datastore_path, wordcounter_plugin):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    headers = {'content-type': 'application/json', 'x-api-key': api_key}
    test_url = url_for('test_endpoint', _external=True)

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html><body><p>one two three four five</p><p>a b</p></body></html>")

    # Plugin processors are accepted in the 'processor' field, and so is their processor_config_*
    res = client.post(url_for("createwatch"), headers=headers, data=json.dumps({
        "url": test_url,
        "processor": "word_counter",
        "fetch_backend": "html_requests",
        "processor_config_word_counter": {"min_word_length": 2},
    }))
    assert res.status_code == 201, res.data
    uuid = res.json.get('uuid')
    wait_for_all_checks(client)

    # 'a' and 'b' are shorter than min_word_length
    res = client.get(url_for("watch", uuid=uuid), headers=headers)
    assert res.status_code == 200
    assert res.json.get('processor') == 'word_counter'
    assert res.json.get('processor_state_word_counter') == {'word_count': 5}
    assert res.json.get('processor_config_word_counter') == {'min_word_length': 2}
    assert res.json.get('processor_config_word_counter_source') == 'watch'
    assert 'processor_state_restock_diff' not in res.json

    res = client.get(url_for("createwatch"), headers=headers)
    assert res.json[uuid].get('processor') == 'word_counter'
    assert res.json[uuid].get('processor_state_word_counter') == {'word_count': 5}
    assert 'processor_config_word_counter' not in res.json[uuid]

    # The snapshot is what the processor returned
    res = client.get(url_for("watchsinglehistory", uuid=uuid, timestamp='latest'), headers=headers)
    assert res.data == b'Words: 5'

    # A GET -> PUT round trip is accepted and doesn't save the read-only fields as config
    data = client.get(url_for("watch", uuid=uuid), headers=headers).json
    res = client.put(url_for("watch", uuid=uuid), headers=headers, data=json.dumps(data))
    assert res.status_code == 200, res.data
    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    with open(os.path.join(watch.data_dir, 'word_counter.json')) as f:
        assert json.load(f) == {'word_counter': {'min_word_length': 2}}

    # The page changes, so does the count
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("<html><body><p>one two three</p></body></html>")
    client.get(url_for("watch", uuid=uuid, recheck=1), headers=headers)
    wait_for_all_checks(client)
    res = client.get(url_for("watch", uuid=uuid), headers=headers)
    assert res.json.get('processor_state_word_counter') == {'word_count': 3}

    delete_all_watches(client)
