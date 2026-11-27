#!/usr/bin/env python3
"""A realtime (Socket.IO) connection is checked for a login on every event, not only when it connects: one that
was opened before a password was set, or with a password that has since been changed, can no longer do anything."""

import time

from flask import g, url_for

from .util import delete_all_watches

SETTINGS_FORM = {
    "requests-time_between_check-minutes": 180,
    "application-fetch_backend": "html_requests",
}


def _forget_cached_user():
    # The test fixtures keep one app context open for the whole test, and Flask-Login caches the user it
    # loaded there. A real server gets a new one per request and per event.
    g.pop('_login_user', None)


def _set_password(c, password):
    _forget_cached_user()
    res = c.post(
        url_for("settings.settings_page"),
        data=dict(SETTINGS_FORM, **{"application-password": password}),
        follow_redirects=True,
    )
    assert b"Password protection enabled." in res.data


def _login(c, password):
    _forget_cached_user()
    res = c.post(url_for("login"), data={"password": password}, follow_redirects=True)
    assert b"/logout" in res.data


def _emit(socketio_client, event, data):
    _forget_cached_user()
    socketio_client.emit(event, data)


def _wait_for_paused(watch, expected, seconds=5):
    # 'checkbox-operation' does its work in a thread
    for _ in range(seconds * 10):
        if bool(watch.get('paused')) == expected:
            return True
        time.sleep(0.1)
    return False


def test_connection_from_before_password_cannot_send_events(app, client, live_server, measure_memory_usage, datastore_path):
    socketio = app.extensions['socketio']
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    watch = datastore.data['watching'][uuid]

    # No password yet, anybody may connect and use it
    anonymous = socketio.test_client(app, flask_test_client=app.test_client(use_cookies=True))
    assert anonymous.is_connected()
    _emit(anonymous, 'checkbox-operation', {'op': 'pause', 'uuids': [uuid]})
    assert _wait_for_paused(watch, True), "Without a password the bulk operation works"
    _emit(anonymous, 'checkbox-operation', {'op': 'unpause', 'uuids': [uuid]})
    assert _wait_for_paused(watch, False)

    # A password appears without the settings page being involved, so nothing has dropped the connection:
    # every event has to be refused by its own check
    datastore.data['settings']['application']['password'] = 'not-a-real-hash'
    try:
        for event, data in (
                ('checkbox-operation', {'op': 'pause', 'uuids': [uuid]}),
                ('watch_operation', {'op': 'pause', 'uuid': uuid}),
                ('watch-subscribe', {'uuids': [uuid]}),
        ):
            stale = socketio.test_client(app, flask_test_client=app.test_client(use_cookies=True))
            assert not stale.is_connected(), "A new anonymous connection is refused once a password is set"

            # Let one in the way the old connection got in, then put the password back
            datastore.data['settings']['application']['password'] = False
            _forget_cached_user()
            stale = socketio.test_client(app, flask_test_client=app.test_client(use_cookies=True))
            assert stale.is_connected()
            datastore.data['settings']['application']['password'] = 'not-a-real-hash'
            stale.get_received()

            _emit(stale, event, data)
            assert not _wait_for_paused(watch, True, seconds=1), f"'{event}' from a connection made before the password must not change anything"
            assert not stale.is_connected(), f"'{event}' from a connection made before the password drops that connection"
            assert not list(socketio.server.manager.get_participants('/', f"watch:{uuid}")), "It was not subscribed to the watch's updates"
    finally:
        datastore.remove_password()

    anonymous.disconnect()
    delete_all_watches(client)


def test_setting_or_changing_password_drops_open_connections(app, client, live_server, measure_memory_usage, datastore_path):
    socketio = app.extensions['socketio']
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    watch = datastore.data['watching'][uuid]

    admin = app.test_client(use_cookies=True)
    other_browser = app.test_client(use_cookies=True)

    try:
        anonymous = socketio.test_client(app, flask_test_client=app.test_client(use_cookies=True))
        assert anonymous.is_connected()

        _set_password(admin, "first-password")
        assert not anonymous.is_connected(), "Setting a password drops the connections opened before it"

        _login(admin, "first-password")
        _login(other_browser, "first-password")
        _forget_cached_user()
        logged_in = socketio.test_client(app, flask_test_client=other_browser)
        assert logged_in.is_connected()
        _emit(logged_in, 'checkbox-operation', {'op': 'pause', 'uuids': [uuid]})
        assert _wait_for_paused(watch, True), "A logged in connection works"
        _emit(logged_in, 'checkbox-operation', {'op': 'unpause', 'uuids': [uuid]})
        assert _wait_for_paused(watch, False)

        _set_password(admin, "second-password")
        assert not logged_in.is_connected(), "Changing the password drops the connections logged in with the old one"

        # And had it stayed open: it is logged in for a password that is no longer the one set
        _login(other_browser, "second-password")
        _forget_cached_user()
        logged_in = socketio.test_client(app, flask_test_client=other_browser)
        assert logged_in.is_connected()
        datastore.data['settings']['application']['password'] = 'changed-behind-its-back'
        _emit(logged_in, 'checkbox-operation', {'op': 'pause', 'uuids': [uuid]})
        assert not _wait_for_paused(watch, True, seconds=1), "A login for an earlier password must not change anything"
        assert not logged_in.is_connected()
    finally:
        # Leave the datastore without a password for the next test
        datastore.remove_password()

    delete_all_watches(client)
