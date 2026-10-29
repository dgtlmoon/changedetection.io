"""
Changing a watch's URL must drop the favicon saved for the old URL (#4569).

Otherwise the old site's icon is kept for up to 24h until it expires, or forever when
the new site has no icon or the watch uses a fetcher that does not fetch favicons.
"""

import json

from flask import url_for

from .util import set_original_response, delete_all_watches

SVG_BASE64 = 'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxIDEiLz4='


def _add_watch_with_favicon(client, url):
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url)
    watch = datastore.data['watching'][uuid]
    watch.ensure_data_dir_exists()
    watch.bump_favicon(url="favicon.svg", favicon_base_64=SVG_BASE64)
    assert watch.get_favicon_filename() == 'favicon.svg'
    return uuid


def _favicon_status(client, uuid):
    return client.get(url_for('static_content', group='favicon', filename=uuid)).status_code


def _edit_watch(client, uuid, url):
    return client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": url,
            "tags": "",
            "headers": "",
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )


def test_ui_edit_url_change_clears_favicon(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    uuid = _add_watch_with_favicon(client, test_url)
    assert _favicon_status(client, uuid) == 200

    # Saving without changing the URL keeps the favicon
    res = _edit_watch(client, uuid, test_url)
    assert b"Updated watch." in res.data
    assert _favicon_status(client, uuid) == 200

    # Changing the URL drops it, so the next check fetches the new site's icon
    res = _edit_watch(client, uuid, test_url + "?other-site=1")
    assert b"Updated watch." in res.data
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    assert watch.get_favicon_filename() is None
    assert watch.favicon_is_expired()
    assert _favicon_status(client, uuid) != 200

    delete_all_watches(client)


def test_api_url_change_clears_favicon(client, live_server, measure_memory_usage, datastore_path):
    api_key = live_server.app.config['DATASTORE'].data['settings']['application'].get('api_access_token')
    test_url = url_for('test_endpoint', _external=True)
    uuid = _add_watch_with_favicon(client, test_url)
    headers = {'x-api-key': api_key, 'content-type': 'application/json'}

    # Updating something other than the URL keeps the favicon
    res = client.put(url_for("watch", uuid=uuid), headers=headers, data=json.dumps({"title": "Renamed"}))
    assert res.status_code == 200, res.data
    assert _favicon_status(client, uuid) == 200

    res = client.put(url_for("watch", uuid=uuid), headers=headers, data=json.dumps({"url": test_url + "?other-site=1"}))
    assert res.status_code == 200, res.data
    watch = client.application.config.get('DATASTORE').data['watching'][uuid]
    assert watch.get_favicon_filename() is None
    assert _favicon_status(client, uuid) != 200

    delete_all_watches(client)
