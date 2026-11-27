#!/usr/bin/env python3
"""A watch signal must not rescan every watch, or build anything, when no browser is connected.

The signal arrives on the worker thread at the start and end of every check, and the dashboard counters are rebuilt
by looping over every watch. With no Socket.IO session open nothing can receive them, so the whole handler is
skipped. With one open, the counters go to everyone and the watch's row only to the browsers that are showing it.
Tested on the handler directly: no live app, no sockets.
"""
import sys
import types

import pytest

from changedetectionio.realtime.socket_server import CoalescedEmit, SignalHandler, has_connected_clients, watch_room


class FakeSocketIO:
    """Flask-SocketIO keeps the socketio.Server at .server; its manager lists who is connected to a namespace,
    and who is in a room of it (a browser joins one room per watch it is showing)."""

    def __init__(self, sessions, showing=()):
        rooms = {None: sessions}
        rooms.update({watch_room(uuid): sessions for uuid in showing})
        participants = lambda namespace, room: iter(rooms.get(room, {}).items() if namespace == '/' else ())
        self.server = types.SimpleNamespace(manager=types.SimpleNamespace(get_participants=participants))
        self.emitted = []

    def emit(self, event, data=None, **kwargs):
        self.emitted.append((event, data, kwargs.get('to')))


def _signal_handler(socketio, datastore):
    """A SignalHandler that is not connected to the app's signals, so the test only drives it directly."""
    handler = SignalHandler.__new__(SignalHandler)
    handler.socketio_instance = socketio
    handler.datastore = datastore
    handler.emit_global_counters = CoalescedEmit(socketio, handler._emit_global_counters)
    handler.emit_queue_size = CoalescedEmit(socketio, handler._emit_queue_size)
    return handler


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
    datastore = FakeDatastore(_watches())

    _signal_handler(socketio, datastore).handle_signal(watch_uuid='a')

    assert datastore.scans == 0
    assert socketio.emitted == []


def test_the_counters_are_still_sent_when_a_browser_is_connected(app_stubs):
    socketio = FakeSocketIO({'sid-1': object()}, showing=['a'])
    datastore = FakeDatastore(_watches())

    _signal_handler(socketio, datastore).handle_signal(watch_uuid='a')

    events = {event: (data, to) for event, data, to in socketio.emitted}
    assert datastore.scans > 0
    assert events['watch_update'][0]['watch']['uuid'] == 'a'
    assert events['watch_update'][1] == watch_room('a'), "The row only goes to the browsers showing that watch"
    assert events['general_stats_update'] == ({'count_errors': 2, 'unread_changes_count': 1}, None)


def test_a_watch_nobody_is_showing_sends_the_counters_but_no_row(app_stubs):
    socketio = FakeSocketIO({'sid-1': object()}, showing=['b'])
    datastore = FakeDatastore(_watches())

    _signal_handler(socketio, datastore).handle_signal(watch_uuid='a')

    events = [event for event, data, to in socketio.emitted]
    assert 'watch_update' not in events
    assert 'general_stats_update' in events and 'checking_now' in events
