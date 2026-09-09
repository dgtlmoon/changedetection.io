#!/usr/bin/env python3
"""PAGE_WATCH_LIMIT - the optional cap on how many watches one instance will hold.

The limit is enforced in datastore.add_watch(), which every add path funnels through, but each
surface has to report it in its own terms: a flash for the UI, a 429 for the API, one flash for
a whole file in the importers, and nothing at all (just a None) where there's no request context.
"""

import json
from flask import url_for
from .util import delete_all_watches


def test_watch_limit_absent_or_junk_means_unlimited(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """No env var, an empty one, or an unparseable one all leave the limit switched off."""
    datastore = live_server.app.config['DATASTORE']

    monkeypatch.delenv('PAGE_WATCH_LIMIT', raising=False)
    assert datastore.watch_limit is None
    assert datastore.watch_limit_reached() is False

    # Junk must not block every add, and must not raise
    monkeypatch.setenv('PAGE_WATCH_LIMIT', 'not-a-number')
    assert datastore.watch_limit is None
    assert datastore.watch_limit_reached() is False

    # Set-but-empty is the same as unset
    monkeypatch.setenv('PAGE_WATCH_LIMIT', '')
    assert datastore.watch_limit is None
    assert datastore.watch_limit_reached() is False


def test_api_create_watch_refused_at_limit(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '1')

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 201

    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": f"{test_url}?second=1"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 429
    assert b'Watch limit reached (1/1 watches)' in res.data
    assert len(datastore.data['watching']) == 1

    delete_all_watches(client)


def test_api_import_refuses_the_whole_batch(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """A 429 from import always means nothing was created, so the same request can be retried."""
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)
    headers = {'x-api-key': api_key, 'content-type': 'text/plain'}

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '3')

    res = client.post(url_for("import"), data=f"{test_url}?a=1\n{test_url}?a=2", headers=headers)
    assert res.status_code == 200
    assert len(res.json) == 2

    # Two more would make four - refused whole rather than importing the one that fits
    res = client.post(url_for("import"), data=f"{test_url}?a=3\n{test_url}?a=4", headers=headers)
    assert res.status_code == 429
    assert b'would exceed it' in res.data
    assert len(datastore.data['watching']) == 2

    # The one that does fit still goes in
    res = client.post(url_for("import"), data=f"{test_url}?a=3", headers=headers)
    assert res.status_code == 200
    assert len(datastore.data['watching']) == 3

    delete_all_watches(client)


def test_quick_watch_add_refused_at_limit(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '1')

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, 'tags': ''},
        follow_redirects=True
    )
    assert b'Watch added' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": f"{test_url}?second=1", 'tags': ''},
        follow_redirects=True
    )
    assert b'Watch limit reached (1/1 watches)' in res.data
    assert b'Watch added' not in res.data
    assert len(datastore.data['watching']) == 1

    delete_all_watches(client)


def test_ui_import_reports_limit_once_and_hands_back_the_rest(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The importer stops at the limit instead of letting add_watch() flash per remaining row."""
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '2')

    urls = "\n".join(f"{test_url}?i={i}" for i in range(5))
    res = client.post(url_for("imports.import_page"), data={"urls": urls}, follow_redirects=True)

    assert res.data.count(b'Watch limit reached') == 1, "The limit should be reported once for the file, not once per row"
    assert len(datastore.data['watching']) == 2
    # 3 unprocessed URLs come back in the textarea to retry once there's room
    assert b'3 Skipped' in res.data
    assert b'i=4' in res.data

    delete_all_watches(client)


def test_clone_refused_at_limit(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Clone used to raise KeyError(None) here, then redirect to an edit page for uuid=None."""
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    uuid = datastore.add_watch(url=test_url)
    monkeypatch.setenv('PAGE_WATCH_LIMIT', '1')

    res = client.post(url_for("ui.form_clone", uuid=uuid), follow_redirects=True)
    assert res.status_code == 200
    assert b'Watch limit reached (1/1 watches)' in res.data
    assert b'Cloned' not in res.data
    assert len(datastore.data['watching']) == 1

    delete_all_watches(client)


def test_over_limit_instance_still_loads_and_edits(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """A limit set below what an install already holds must only block *new* watches.

    Everything already there keeps loading from disk and stays editable - the limit is not
    retroactive and never hides or drops a watch.
    """
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    monkeypatch.delenv('PAGE_WATCH_LIMIT', raising=False)
    uuids = [datastore.add_watch(url=f"{test_url}?i={i}") for i in range(3)]
    assert all(uuids)

    # Now cap it well below what's already stored
    monkeypatch.setenv('PAGE_WATCH_LIMIT', '1')
    assert datastore.watch_limit_reached() is True

    # Re-reading from disk is not gated by the limit
    datastore._load_watches()
    assert len(datastore.data['watching']) == 3

    # Still all listed
    assert client.get(url_for("watchlist.index")).status_code == 200
    res = client.get(url_for("createwatch"), headers={'x-api-key': api_key})
    assert len(res.json) == 3

    # And still editable
    res = client.put(
        url_for("watch", uuid=uuids[0]),
        data=json.dumps({"title": "Still editable"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 200
    assert datastore.data['watching'][uuids[0]].get('title') == "Still editable"

    # Only adding is refused
    res = client.post(
        url_for("createwatch"),
        data=json.dumps({"url": f"{test_url}?new=1"}),
        headers={'content-type': 'application/json', 'x-api-key': api_key},
    )
    assert res.status_code == 429
    assert len(datastore.data['watching']) == 3

    delete_all_watches(client)


def test_limit_shown_in_settings_info_tab(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The Info tab names the limit only when one is configured."""
    monkeypatch.delenv('PAGE_WATCH_LIMIT', raising=False)
    res = client.get(url_for("settings.settings_page"))
    assert b'Maximum number of page watches' not in res.data

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '42')
    res = client.get(url_for("settings.settings_page"))
    assert b'Maximum number of page watches' in res.data
    assert b'42' in res.data


def test_limit_reported_without_a_request_context(client, live_server, measure_memory_usage, datastore_path, monkeypatch, mocker):
    """The CLI (-u) and the API's background import thread call add_watch() with no request
    context, where flash() raises RuntimeError instead of reporting anything."""
    datastore = live_server.app.config['DATASTORE']
    test_url = url_for('test_endpoint', _external=True)

    monkeypatch.setenv('PAGE_WATCH_LIMIT', '1')
    assert datastore.add_watch(url=test_url)

    # pytest-flask pushes a request context around every test, so take it away
    mocker.patch('changedetectionio.store.has_request_context', return_value=False)

    assert datastore.add_watch(url=f"{test_url}?second=1") is None
    assert len(datastore.data['watching']) == 1

    delete_all_watches(client)
