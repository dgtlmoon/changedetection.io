"""
The API rejects broken Jinja2 in url, link_to_open, body and headers, the same as the edit form.

Before, a broken template saved through the API was only found at fetch time and the watch then
failed on every check.
"""

import json

from flask import url_for

from .util import delete_all_watches


def _headers(live_server):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    return {'x-api-key': api_key, 'content-type': 'application/json'}


def test_api_create_rejects_broken_jinja2(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_endpoint', _external=True)
    headers = _headers(live_server)

    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": test_url, "method": "POST", "body": "{{ unclosed"}))
    assert res.status_code == 400
    assert b"body: Invalid template syntax" in res.data

    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": test_url, "headers": {"x-bad": "{% endfor %}"}}))
    assert res.status_code == 400
    assert '"x-bad" header' in res.get_json()

    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": test_url + "?q={{ broken("}))
    assert res.status_code == 400
    assert b"url: Invalid template syntax" in res.data

    assert len(live_server.app.config['DATASTORE'].data['watching']) == 0

    # Valid templates and text that only looks like Jinja2 are accepted
    res = client.post(url_for("createwatch"), headers=headers,
                      data=json.dumps({"url": test_url, "method": "POST",
                                       "body": 'q={%22key%22:1}',
                                       "headers": {"x-ok": "{{ 2*2 }}"}}))
    assert res.status_code == 201, res.data

    delete_all_watches(client)


def test_api_update_rejects_broken_jinja2(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_endpoint', _external=True)
    headers = _headers(live_server)
    uuid = live_server.app.config['DATASTORE'].add_watch(url=test_url)

    res = client.put(url_for("watch", uuid=uuid), headers=headers,
                     data=json.dumps({"method": "POST", "body": "{{ unclosed"}))
    assert res.status_code == 400
    assert b"body: Invalid template syntax" in res.data

    res = client.put(url_for("watch", uuid=uuid), headers=headers,
                     data=json.dumps({"link_to_open": "https://example.com/{% if %}"}))
    assert res.status_code == 400
    assert b"link_to_open: Invalid template syntax" in res.data

    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    assert not watch.get('body')
    assert not watch.get('link_to_open')

    res = client.put(url_for("watch", uuid=uuid), headers=headers,
                     data=json.dumps({"method": "POST", "body": 'q={%22key%22:1}'}))
    assert res.status_code == 200, res.data
    assert watch.get('body') == 'q={%22key%22:1}'

    delete_all_watches(client)
