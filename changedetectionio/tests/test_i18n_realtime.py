#!/usr/bin/env python3

"""The watch list realtime updates must follow the browser's display language.

#4481 - the bulk action toast was always in English.
#4482 - the "last checked" / "last changed" columns went back to English as soon
        as a row was updated over the socket.

Both are the same root cause: the text is built outside of a request (a
background thread / a socket.io emit) and flask_babel has no request to read the
locale from there, so it silently used the English string.

See changedetectionio/i18n_thread.py and changedetectionio/realtime/socket_server.py
"""

import time

from flask import url_for

from .util import delete_all_watches, set_modified_response, set_original_response, wait_for_all_checks


def _set_language(client, locale):
    """Use the real language switcher, so the session holds the locale."""
    # A first request, so that the session cookie exists - the language switcher
    # refuses to store the locale without one.
    client.get(url_for('watchlist.index'))
    res = client.post(url_for('set_language', locale=locale), follow_redirects=True)
    assert res.status_code == 200

    with client.session_transaction() as sess:
        assert sess.get('locale') == locale, "The display language was not stored in the session"


def _add_watch(client):
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )
    assert res.status_code == 200
    # The flash message is translated too, so check the datastore instead of the text.
    assert len(live_server_watches()) == 1


def live_server_watches():
    from changedetectionio.flask_app import app
    return app.config.get('DATASTORE').data['watching']


def _wait_for_event(socketio_test_client, name, timeout=20):
    """Wait for one event with the given name and return its payload."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for event in socketio_test_client.get_received():
            if event['name'] == name:
                return event['args'][0]
        time.sleep(0.25)

    return None


def test_bulk_action_toast_uses_the_display_language(live_server, client, measure_memory_usage, datastore_path):
    """#4481 - the toast of a bulk action must be in the browser's language.

    The message is built in a background thread, which has no request to read
    the locale from, so it used to come out in English on a translated page.
    """
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']

    set_original_response(datastore_path=datastore_path)
    _add_watch(client)
    wait_for_all_checks(client)

    _set_language(client, 'ja')

    socketio_test_client = socketio.test_client(app, flask_test_client=client)
    assert socketio_test_client.is_connected(), "Failed to connect to Socket.IO server"

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching'].keys()))

    socketio_test_client.emit('checkbox-operation', {'op': 'pause', 'uuids': [uuid]})

    toast = _wait_for_event(socketio_test_client, 'toast')
    assert toast, "No toast was received for the bulk action"

    message = toast.get('message')
    assert message, "The toast had no message"
    assert 'ウォッチ' in message, f"The toast was not translated: '{message}'"

    delete_all_watches(client)


def test_watch_list_update_uses_the_display_language(live_server, client, measure_memory_usage, datastore_path):
    """#4482 - the live "last changed" / "last checked" text must be translated.

    The row is rendered in the browser's language on the first page load, but
    the socket update overwrote it with the English text.
    """
    from changedetectionio.flask_app import app
    socketio = app.extensions['socketio']

    set_original_response(datastore_path=datastore_path)

    _set_language(client, 'ja')

    socketio_test_client = socketio.test_client(app, flask_test_client=client)
    assert socketio_test_client.is_connected(), "Failed to connect to Socket.IO server"

    # The first check of a new watch emits a watch_update - the watch has one
    # snapshot only, so "last changed" is the translated "Not yet".
    _add_watch(client)
    wait_for_all_checks(client)

    update = _wait_for_event(socketio_test_client, 'watch_update')
    assert update, "No watch_update was received"

    watch = update['watch']
    assert watch.get('last_changed_text') == '未実施', \
        f"The 'last changed' text was not translated: '{watch.get('last_changed_text')}'"

    # And the same for a row that has a change now - the relative time is
    # rendered by timeago, which has a translation for it as well.
    set_modified_response(datastore_path=datastore_path)
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    update = None
    deadline = time.time() + 20
    while time.time() < deadline:
        for event in socketio_test_client.get_received():
            if event['name'] == 'watch_update':
                update = event['args'][0]
        if update:
            break
        time.sleep(0.25)

    assert update, "No watch_update was received after the recheck"

    last_changed_text = update['watch'].get('last_changed_text')
    assert last_changed_text != 'Not yet', "The 'last changed' text went back to English"
    assert not last_changed_text.isascii(), \
        f"The 'last changed' text is not translated: '{last_changed_text}'"

    delete_all_watches(client)
