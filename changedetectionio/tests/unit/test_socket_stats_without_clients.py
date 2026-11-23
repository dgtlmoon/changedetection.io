#!/usr/bin/env python3
"""handle_watch_update must not rescan every watch when no browser is connected.

It runs on the worker thread at the start and end of every check and rebuilds the dashboard counters by looping
over every watch twice. With no Socket.IO session open nothing can receive them, so the whole handler is skipped.
Tested on the function directly: no live app, no sockets.
"""
import sys
import types

import pytest

from changedetectionio.realtime.socket_server import handle_watch_update, has_connected_clients


class FakeSocketIO:
    """Flask-SocketIO keeps the socketio.Server at .server; its manager lists who is connected to a namespace."""

    def __init__(self, sessions):
        participants = lambda namespace, room: iter(sessions.items() if namespace == '/' and room is None else ())
        self.server = types.SimpleNamespace(manager=types.SimpleNamespace(get_participants=participants))
        self.emitted = []

    def emit(self, event, data=None, **kwargs):
        self.emitted.append((event, data))


class FakeWatch(dict):
    history_n = 2
    last_changed = 0
    has_unviewed = False

    def compile_error_texts(self):
        return self.get('last_error') or ''

    def get_favicon_filename(self):
        return None


class FakeDatastore:
    unread_changes_count = 1

    def __init__(self, watches):
        self._watches = watches
        self.scans = 0

    @property
    def data(self):
        # handle_watch_update catches and logs its own errors, so count the reads instead of raising on them
        self.scans += 1
        return {'watching': self._watches}


@pytest.fixture
def app_stubs(monkeypatch):
    """handle_watch_update imports these lazily; keep the real app out of the unit test."""
    fake_app = types.ModuleType('changedetectionio.flask_app')
    fake_app.update_q = types.SimpleNamespace(get_queued_uuids=lambda: [])
    fake_app._jinja2_filter_datetime = lambda watch: 'never'
    fake_app._jinja2_filter_datetimestamp = lambda ts: 'never'
    monkeypatch.setitem(sys.modules, 'changedetectionio.flask_app', fake_app)
    from changedetectionio import worker_pool
    monkeypatch.setattr(worker_pool, 'get_running_uuids', lambda: set())


def _watches():
    return {
        'a': FakeWatch(uuid='a', last_error='boom'),
        'b': FakeWatch(uuid='b', last_error=False),
        'c': FakeWatch(uuid='c', last_error='timeout'),
    }


def test_no_session_means_no_clients():
    assert has_connected_clients(FakeSocketIO({})) is False


def test_an_open_session_means_clients():
    assert has_connected_clients(FakeSocketIO({'sid-1': object()})) is True


def test_a_client_registered_with_the_real_socketio_manager_counts():
    # Against the library itself, so a change to how python-socketio records participants shows up here.
    import socketio
    server = socketio.Server()
    wrapper = types.SimpleNamespace(server=server)
    assert has_connected_clients(wrapper) is False

    sid = server.manager.connect('eio-sid-1', '/')
    assert has_connected_clients(wrapper) is True

    server.manager.disconnect(sid, '/')
    assert has_connected_clients(wrapper) is False


def test_an_unrecognised_layout_counts_as_connected():
    # No .server (or not created yet): behave as before rather than going quiet.
    assert has_connected_clients(object()) is True
    assert has_connected_clients(types.SimpleNamespace(server=None)) is True


def test_nothing_is_scanned_or_emitted_when_nobody_is_connected(app_stubs):
    socketio = FakeSocketIO({})
    watches = _watches()
    datastore = FakeDatastore(watches)

    handle_watch_update(socketio, watch=watches['a'], datastore=datastore)

    assert datastore.scans == 0
    assert socketio.emitted == []


def test_the_counters_are_still_sent_when_a_browser_is_connected(app_stubs):
    socketio = FakeSocketIO({'sid-1': object()})
    watches = _watches()
    datastore = FakeDatastore(watches)

    handle_watch_update(socketio, watch=watches['a'], datastore=datastore)

    events = dict(socketio.emitted)
    assert datastore.scans > 0
    assert events['watch_update']['watch']['uuid'] == 'a'
    assert events['general_stats_update'] == {'count_errors': 2, 'unread_changes_count': 1}
