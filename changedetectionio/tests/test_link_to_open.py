"""
Tests for the optional per-watch "Link to Open" (`link_to_open`).

A watch may point at something that is useless in a browser - an API endpoint or an RSS
feed - while the human-readable page lives somewhere else. `link_to_open` stores that page,
and every "go to the site" affordance (watch list, history/preview header, the
{{watch_open_url}} notification token) uses it in preference to the watched URL.
"""

import os

from flask import url_for

from .util import set_original_response, set_modified_response, wait_for_all_checks, \
    wait_for_notification_endpoint_output

OPEN_URL = "https://example.com/the-real-human-page"


def _add_watch(client, test_url):
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)


def _edit_watch(client, test_url, **extra):
    data = {
        "url": test_url,
        "tags": "",
        "headers": "",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y",
    }
    data.update(extra)
    return client.post(url_for("ui.ui_edit.edit_page", uuid="first"), data=data, follow_redirects=True)


def test_link_to_open_is_saved_and_used_in_the_watch_list(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    _add_watch(client, test_url)

    # Without an override, the watch list links to the watched URL
    res = client.get(url_for("watchlist.index"))
    assert f'href="{test_url}"'.encode('utf-8') in res.data
    assert OPEN_URL.encode('utf-8') not in res.data

    res = _edit_watch(client, test_url, link_to_open=OPEN_URL)
    assert b"Updated watch." in res.data

    # It round-trips back into the edit form
    res = client.get(url_for("ui.ui_edit.edit_page", uuid="first"))
    assert OPEN_URL.encode('utf-8') in res.data

    # ...and the watch list now points at it instead of the watched URL
    res = client.get(url_for("watchlist.index"))
    assert f'href="{OPEN_URL}"'.encode('utf-8') in res.data
    assert f'href="{test_url}"'.encode('utf-8') not in res.data


def test_link_to_open_used_in_history_header(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    _add_watch(client, test_url)

    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    assert b"Updated watch." in _edit_watch(client, test_url, link_to_open=OPEN_URL).data

    uuid = next(iter(client.application.config.get('DATASTORE').data['watching'].keys()))

    # Top-of-page link on the history/diff page
    res = client.get(url_for("ui.ui_diff.diff_history_page", uuid=uuid))
    assert f'class="current-diff-url" href="{OPEN_URL}"'.encode('utf-8') in res.data

    # ...and on the preview page
    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid))
    assert f'class="current-diff-url" href="{OPEN_URL}"'.encode('utf-8') in res.data


def test_invalid_link_to_open_is_rejected(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    _add_watch(client, test_url)

    res = _edit_watch(client, test_url, link_to_open="javascript:alert(1)")
    assert b"Updated watch." not in res.data
    assert b"Watch protocol is not permitted or invalid URL format" in res.data

    # Blank is fine - it means "use the watched URL"
    res = _edit_watch(client, test_url, link_to_open="")
    assert b"Updated watch." in res.data
    watch = list(client.application.config.get('DATASTORE').data['watching'].values())[0]
    assert watch.open_link == test_url


def test_watch_open_url_notification_token(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    notification_file = os.path.join(datastore_path, "notification.txt")
    if os.path.isfile(notification_file):
        os.unlink(notification_file)

    test_url = url_for('test_endpoint', _external=True)
    _add_watch(client, test_url)

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')

    res = _edit_watch(
        client,
        test_url,
        link_to_open=OPEN_URL,
        notification_urls=notification_url,
        notification_title="Test",
        notification_body="watched={{watch_url}}\nopen={{watch_open_url}}",
        notification_format="text",
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(notification_file, 'r') as f:
        body = f.read()

    assert f"watched={test_url}" in body
    assert f"open={OPEN_URL}" in body
    os.unlink(notification_file)


def test_watch_open_url_token_falls_back_to_watch_url(client, live_server, measure_memory_usage, datastore_path):
    """With no 'Link to Open' set, {{watch_open_url}} must still render the watched URL."""
    set_original_response(datastore_path=datastore_path)
    notification_file = os.path.join(datastore_path, "notification.txt")
    if os.path.isfile(notification_file):
        os.unlink(notification_file)

    test_url = url_for('test_endpoint', _external=True)
    _add_watch(client, test_url)

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')

    res = _edit_watch(
        client,
        test_url,
        notification_urls=notification_url,
        notification_title="Test",
        notification_body="open={{watch_open_url}}",
        notification_format="text",
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(notification_file, 'r') as f:
        body = f.read()

    assert f"open={test_url}" in body
    os.unlink(notification_file)
