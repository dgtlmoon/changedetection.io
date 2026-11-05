#!/usr/bin/env python3
"""llm_prefilter is gone (it was never set or read). Older watches still have "llm_prefilter": null stored, which the
API keeps hiding (it's in SYSTEM_MANAGED_NON_SPEC_FIELDS), so a GET -> PUT round trip still works without a datastore
update."""
import json

from flask import url_for
from .util import delete_all_watches


def test_stored_llm_prefilter_is_ignored(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('api_access_token')
    uuid = datastore.add_watch(url='https://example.com/menu', extras={'paused': True})
    assert 'llm_prefilter' not in datastore.data['watching'][uuid], "new watches don't get it any more"

    # What an existing install has stored
    datastore.data['watching'][uuid]['llm_prefilter'] = None

    # GET doesn't show it, sending the GET back as a PUT is accepted, and a PUT that sends it is ignored
    headers = {'x-api-key': api_key, 'content-type': 'application/json'}
    res = client.get(url_for('watch', uuid=uuid), headers=headers)
    assert res.status_code == 200 and 'llm_prefilter' not in res.json
    res = client.put(url_for('watch', uuid=uuid), headers=headers, data=json.dumps(res.json))
    assert res.status_code == 200, res.data
    res = client.put(url_for('watch', uuid=uuid), headers=headers, data=json.dumps({'llm_prefilter': 'div.hacked'}))
    assert res.status_code == 200, res.data
    assert datastore.data['watching'][uuid].get('llm_prefilter') is None

    delete_all_watches(client)
