from flask_socketio import SocketIO

import time
import os
from loguru import logger
from blinker import signal

from changedetectionio import strtobool


# A browser tells the server which watches it is showing (the 'watch-subscribe' event) and joins one room per watch.
# Per-watch events go to that watch's room only, so a page of 200 rows is not sent - and the server does not build -
# updates for the thousands of watches it is not showing.
WATCH_ROOM_PREFIX = 'watch:'
# More than any page shows, stops one connection joining an unbounded number of rooms
MAX_WATCH_SUBSCRIPTIONS = 2000
# Room for a selection of 200,000 watches in one bulk operation message
MAX_SOCKET_MESSAGE_BYTES = 8 * 1024 * 1024
# The counters in the page header (queue size, checking now, unread, errors) are sent at most this often
GLOBAL_COUNTERS_MIN_INTERVAL_SECONDS = 1.0


def watch_room(watch_uuid):
    return f"{WATCH_ROOM_PREFIX}{watch_uuid}"


# The rendered row of a watch goes to the pages listing it. A list filtered by a group has that group in the row's
# links (Edit, Recheck, pause ... come back to the filtered list), and an app served under a sub-path
# (USE_X_SETTINGS with X-Forwarded-Prefix, e.g. example.com/changedetection/) has that path at the start of every
# address in the row. So there is one room per watch, group and sub-path: a page joins the one for the group it is
# filtered by ('' for none) and the sub-path it was reached under ('' for none), and is sent the row rendered for
# those. The row is rendered from a worker thread, outside any request, so nothing else says which sub-path the
# page's addresses need.
WATCH_ROW_ROOM_PREFIX = 'watch-row:'
# watch uuid -> the (group filter, sub-path) pairs of the pages that have asked for its row
_row_filters_shown = {}


def watch_row_room(watch_uuid, tag_uuid='', url_prefix=''):
    return f"{WATCH_ROW_ROOM_PREFIX}{watch_uuid}:{tag_uuid or ''}:{url_prefix or ''}"


def connection_url_prefix():
    """The sub-path the browser of this Socket.IO connection reaches the app under, '' when there is none. Read
    from the request the connection was made with: the script root that ProxyFix made of X-Forwarded-Prefix, or
    the header itself where the connection's request did not pass through ProxyFix. Only the rows sent to pages
    under the same sub-path are rendered with it (see watch_row_room), so it reaches nobody else's page."""
    import os
    import re
    from flask import request
    prefix = request.script_root or ''
    if not prefix and os.getenv('USE_X_SETTINGS'):
        prefix = request.headers.get('X-Forwarded-Prefix', '')
    prefix = prefix.rstrip('/')
    # A path and nothing else
    if not prefix or len(prefix) > 200 or not re.fullmatch(r'(/[A-Za-z0-9._~-]+)+', prefix):
        return ''
    return prefix


def watch_has_viewers(socketio, watch_uuid):
    """True when at least one connected browser is showing this watch. Same fallback as has_connected_clients()."""
    try:
        return next(iter(socketio.server.manager.get_participants('/', watch_room(watch_uuid))), None) is not None
    except AttributeError:
        return True


class CoalescedEmit:
    """Runs emit_fn straight away, then at most once per interval: calls that arrive in between collapse into a
    single run at the end of the interval, so the last state always lands. emit_fn reads the current values itself."""

    def __init__(self, socketio, emit_fn, interval=GLOBAL_COUNTERS_MIN_INTERVAL_SECONDS):
        import threading
        self.socketio = socketio
        self.emit_fn = emit_fn
        self.interval = interval
        self._lock = threading.Lock()
        self._last_run = 0.0
        self._pending = False

    def __call__(self):
        with self._lock:
            if self._pending:
                return
            wait = self._last_run + self.interval - time.monotonic()
            if wait > 0:
                self._pending = True
            else:
                self._last_run = time.monotonic()

        if wait > 0:
            self.socketio.start_background_task(self._run_later, wait)
        else:
            self._run()

    def _run_later(self, wait):
        self.socketio.sleep(wait)
        with self._lock:
            self._pending = False
            self._last_run = time.monotonic()
        self._run()

    def _run(self):
        try:
            self.emit_fn()
        except Exception as e:
            logger.error(f"Socket.IO error in {getattr(self.emit_fn, '__name__', 'coalesced emit')}: {str(e)}")


class SignalHandler:
    """A standalone class to receive signals"""

    def __init__(self, socketio_instance, datastore):
        self.socketio_instance = socketio_instance
        self.datastore = datastore

        # Both are rebuilt from the whole datastore / queue, and signals arrive in bursts (every queue put and get,
        # the start and end of every check), so they are sent at most once per interval.
        self.emit_global_counters = CoalescedEmit(socketio_instance, self._emit_global_counters)
        self.emit_queue_size = CoalescedEmit(socketio_instance, self._emit_queue_size)

        # Connect to the watch_check_update signal
        from changedetectionio.flask_app import watch_check_update as wcc
        wcc.connect(self.handle_signal, weak=False)
        #        logger.info("SignalHandler: Connected to signal from direct import")

        # Connect to the queue_length signal
        queue_length_signal = signal('queue_length')
        queue_length_signal.connect(self.handle_queue_length, weak=False)
        #       logger.info("SignalHandler: Connected to queue_length signal")

        watch_delete_signal = signal('watch_deleted')
        watch_delete_signal.connect(self.handle_deleted_signal, weak=False)

        watch_favicon_bumped_signal = signal('watch_favicon_bump')
        watch_favicon_bumped_signal.connect(self.handle_watch_bumped_favicon_signal, weak=False)

        watch_small_status_comment_signal = signal('watch_small_status_comment')
        watch_small_status_comment_signal.connect(self.handle_watch_small_status_update, weak=False)

        # The AI summary generator runs on a background thread; this lets the browser skip
        # polling for the result.
        llm_summary_ready_signal = signal('llm_summary_ready')
        llm_summary_ready_signal.connect(self.handle_llm_summary_ready, weak=False)

        # Connect to the notification_event signal
        notification_event_signal = signal('notification_event')
        notification_event_signal.connect(self.handle_notification_event, weak=False)
        logger.info("SignalHandler: Connected to notification_event signal")

        # One-shot stats refresh for bulk operations that deliberately skip the per-watch
        # signal (see set_last_viewed(send_signal=False)) — n signals would mean n full
        # rescans of every watch plus 3n broadcasts.
        general_stats_signal = signal('general_stats_update')
        general_stats_signal.connect(self.handle_general_stats_update, weak=False)

        # Many watches changed in one go (a bulk operation, a batch put into the queue)
        watches_changed_signal = signal('watches_changed')
        watches_changed_signal.connect(self.handle_watches_changed, weak=False)

    def handle_watches_changed(self, *args, **kwargs):
        """One signal for many watches: update the rows that browsers are showing, which is a page or two of them
        however many changed, and the counters once."""
        if not has_connected_clients(self.socketio_instance):
            return
        self.emit_global_counters()
        shown = [u for u in kwargs.get('uuids') or [] if watch_has_viewers(self.socketio_instance, u)]
        if not shown:
            return

        # Read the queue and the running list once for all of them, the queue can be very long
        from changedetectionio.flask_app import update_q
        from changedetectionio import worker_pool
        queued_uuids = set(update_q.get_queued_uuids())
        running_uuids = set(worker_pool.get_running_uuids())
        for watch_uuid in shown:
            self.send_watch_row(watch_uuid, kwargs.get('app_context'), queued_uuids=queued_uuids, running_uuids=running_uuids)

    def handle_general_stats_update(self, *args, **kwargs):
        """Emit the global counters, without touching any individual row.

        Sent after a bulk operation. The tab that triggered it is usually reloading anyway;
        this is for OTHER open tabs so their unread/error counters don't sit stale.
        Note their ROWS still keep a stale 'unviewed' class until the row resync lands —
        tracked separately, this only fixes the counters.
        """
        if has_connected_clients(self.socketio_instance):
            self.emit_global_counters()

    def _emit_global_counters(self):
        """The counters every page shows, whichever watches it lists. Loops over every watch, see emit_global_counters."""
        from changedetectionio import worker_pool

        errored_count = sum(1 for w in self.datastore.data['watching'].values() if w.get('last_error'))
        self.socketio_instance.emit("general_stats_update", {
            'count_errors': errored_count,
            'unread_changes_count': self.datastore.unread_changes_count,
        })
        # The set of running UUIDs changes exactly when a worker claims/releases a watch, and the watch signal
        # fires at both of those moments.
        self.socketio_instance.emit("checking_now", {
            "count": len(worker_pool.get_running_uuids()),
            "event_timestamp": time.time()
        })
        logger.trace("Socket.IO: Emitted general_stats_update and checking_now")

    def _emit_queue_size(self):
        from changedetectionio.flask_app import update_q

        self.socketio_instance.emit("queue_size", {
            "q_length": update_q.qsize(),
            "event_timestamp": time.time()
        })

    def handle_watch_small_status_update(self, *args, **kwargs):
        """Small simple status update, for example 'Connecting...'"""
        watch_uuid = kwargs.get('watch_uuid')
        status = kwargs.get('status')

        if watch_uuid and status:
            logger.debug(f"Socket.IO: Received watch small status update '{status}' for UUID {watch_uuid}")
            # Only to the browsers showing this watch
            self.socketio_instance.emit("watch_small_status_comment", {
                "uuid": watch_uuid,
                "status": status,
                "event_timestamp": time.time()
            }, to=watch_room(watch_uuid))



    def handle_signal(self, *args, **kwargs):
        logger.trace(f"SignalHandler: Signal received with {len(args)} args and {len(kwargs)} kwargs")
        # This runs on the worker thread at the start and end of every check, and on every queue put. With nobody
        # connected there is nobody to send anything to, and a browser that connects later gets its numbers from
        # the rendered page.
        if not has_connected_clients(self.socketio_instance):
            return

        # The counters are for every page
        self.emit_global_counters()

        # The row itself is only for the browsers showing it, with none there is nothing to build
        watch_uuid = kwargs.get('watch_uuid')
        app_context = kwargs.get('app_context')
        if not watch_uuid or not watch_has_viewers(self.socketio_instance, watch_uuid):
            return

        self.send_watch_row(watch_uuid, app_context)

    def send_watch_row(self, watch_uuid, app_context=None, **row_state):
        watch = self.datastore.data['watching'].get(watch_uuid)
        if watch:
            if app_context:
                # note
                with app_context.app_context():
                    with app_context.test_request_context():
                        # Forward to handle_watch_update with the watch parameter
                        handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore, **row_state)
            else:
                handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore, **row_state)

            logger.trace(f"Signal handler processed watch UUID {watch_uuid}")
        else:
            logger.warning(f"Watch UUID {watch_uuid} not found in datastore")

    def handle_watch_bumped_favicon_signal(self, *args, **kwargs):
        watch_uuid = kwargs.get('watch_uuid')
        if watch_uuid:
            # Only to the browsers showing this watch
            self.socketio_instance.emit("watch_bumped_favicon", {
                "uuid": watch_uuid,
                "event_timestamp": time.time()
            }, to=watch_room(watch_uuid))
        logger.debug(f"Watch UUID {watch_uuid} got its favicon updated")

    def handle_llm_summary_ready(self, *args, **kwargs):
        """An on-demand AI change summary finished generating (successfully or not).

        Only identifiers are broadcast: the client turns this into one authenticated request to
        the /llm-summary poll route, so the summary text itself never goes to every connected
        browser. Clients that do not care about this watch simply ignore the event.
        """
        watch_uuid = kwargs.get('watch_uuid')
        if watch_uuid:
            self.socketio_instance.emit("llm_summary_ready", {
                "uuid": watch_uuid,
                "from_version": kwargs.get('from_version'),
                "to_version": kwargs.get('to_version'),
                "event_timestamp": time.time()
            })
        logger.debug(f"Watch UUID {watch_uuid} AI summary job settled")

    def handle_deleted_signal(self, *args, **kwargs):
        watch_uuid = kwargs.get('watch_uuid')
        if watch_uuid:
            # Emit the queue size to all connected clients
            self.socketio_instance.emit("watch_deleted", {
                "uuid": watch_uuid,
                "event_timestamp": time.time()
            })
        logger.debug(f"Watch UUID {watch_uuid} was deleted")

    def handle_queue_length(self, *args, **kwargs):
        """The queue grew or shrank. Sent to all clients, see emit_queue_size for how often."""
        if has_connected_clients(self.socketio_instance):
            self.emit_queue_size()

    def handle_notification_event(self, *args, **kwargs):
        """Handle notification_event signal and emit to all clients"""
        try:
            watch_uuid = kwargs.get('watch_uuid')
            logger.debug(f"SignalHandler: Notification event received for watch UUID: {watch_uuid}")

            # Emit the notification event to all connected clients
            self.socketio_instance.emit("notification_event", {
                "watch_uuid": watch_uuid,
                "event_timestamp": time.time()
            })

            logger.trace(f"Socket.IO: Emitted notification_event for watch UUID {watch_uuid}")

        except Exception as e:
            logger.error(f"Socket.IO error in handle_notification_event: {str(e)}")



def socket_client_is_allowed(datastore):
    """The same rule as the pages: with a password set, only a logged in browser. Called for the connection and
    again for every event - a connection that was let in before a password was set, or with a password that has
    since been changed, is not a login any more (see User.get_id() for how the login follows the password)."""
    from flask_login import current_user

    has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)
    return not has_password_enabled or current_user.is_authenticated


def login_optionally_required_for_event(datastore):
    """For Socket.IO event handlers, what @login_optionally_required is for the pages. A connection that is no
    longer allowed is dropped; the browser reconnects by itself and is then checked by the 'connect' handler."""
    from functools import wraps

    def decorator(handler):
        @wraps(handler)
        def checked_handler(*args, **kwargs):
            from flask_socketio import disconnect

            if not socket_client_is_allowed(datastore):
                logger.warning("Socket.IO: Dropping a connection that is not logged in for the current password")
                disconnect()
                return None
            return handler(*args, **kwargs)
        return checked_handler
    return decorator


def disconnect_all_clients(app):
    """Drops every open connection, for when the password is set or changed: those connections were let in under
    the old rules and would keep receiving watch updates. Each browser reconnects and is checked again."""
    socketio = app.extensions.get('socketio')
    if not socketio:
        return
    try:
        sids = [sid for sid, _eio_sid in socketio.server.manager.get_participants('/', None)]
    except AttributeError:
        return
    for sid in sids:
        try:
            socketio.server.disconnect(sid)
        except Exception as e:
            logger.error(f"Socket.IO error disconnecting a client after a password change: {str(e)}")


def has_connected_clients(socketio):
    """True when at least one client has completed the Socket.IO connect on the default namespace.

    Asks the Socket.IO manager (the same record emit() sends to), so test clients and any transport count, and a
    client that was rejected by the connect handler or is still handshaking does not.

    If that can't be read (an unexpected Flask-SocketIO layout, or the server not created yet) this returns True, so
    callers fall back to always emitting rather than silently going quiet.
    """
    try:
        return next(iter(socketio.server.manager.get_participants('/', None)), None) is not None
    except AttributeError:
        return True


def render_watch_list_row(watch, datastore, tag_uuid='', queued_uuids=None, url_prefix=''):
    """The watch's row of the watch list, from the template the page itself is made with
    (watch-overview-single-row.html with blueprint/watchlist/row_context.py), as the list filtered by `tag_uuid`
    shows it. Mostly called from a worker thread at the end of a check, where there is no request to render in.
    url_prefix: the sub-path the page is served under, so the row's addresses (links, images, form actions) start
    with it as they do in the page."""
    from flask import render_template
    from changedetectionio.blueprint.watchlist.row_context import watch_row_context

    def render():
        return render_template('watch-overview-single-row.html', watch=watch,
                               **watch_row_context(datastore, active_tag_uuid=tag_uuid or None, queued_uuids=queued_uuids))

    # The row reads the group from the request too (the Recheck button), so always in a request of that list
    from changedetectionio.flask_app import app
    with app.test_request_context(query_string={'tag': tag_uuid} if tag_uuid else None,
                                  environ_overrides={'SCRIPT_NAME': url_prefix} if url_prefix else None):
        return render()


def send_watch_list_row(socketio, watch, datastore, queued_uuids=None):
    """Send the watch's rendered row to the pages that list it, once for each group filter among them."""
    uuid = watch.get('uuid')
    for shown in list(_row_filters_shown.get(uuid, ())):
        tag_uuid, url_prefix = shown
        room = watch_row_room(uuid, tag_uuid, url_prefix)
        try:
            has_pages = next(iter(socketio.server.manager.get_participants('/', room)), None) is not None
        except AttributeError:
            has_pages = True
        if not has_pages:
            # The pages that asked have gone
            _row_filters_shown[uuid].discard(shown)
            if not _row_filters_shown[uuid]:
                del _row_filters_shown[uuid]
            continue
        try:
            html = render_watch_list_row(watch, datastore, tag_uuid=tag_uuid, queued_uuids=queued_uuids, url_prefix=url_prefix)
        except Exception as e:
            logger.error(f"Socket.IO: could not render the watch list row of {uuid}: {str(e)}")
            continue
        socketio.emit("watch_row", {'uuid': uuid, 'html': html, 'event_timestamp': time.time()}, to=room)


def handle_watch_update(socketio, **kwargs):
    """Tell the browsers that are showing a watch that it was updated (see watch_room).

    Two things go out: "watch_update", a few flags for any page about the watch (the edit, preview and history
    pages show that it is being checked), and "watch_row" for the watch list, the row as the list draws it. The
    list used to be pieced together in the browser from fields sent here (texts, counts, error markup), which is
    what the row replaces."""
    try:
        watch = kwargs.get('watch')

        from changedetectionio.flask_app import update_q
        from changedetectionio import worker_pool

        # Watches that are currently running, and those in the queue. A caller sending many rows passes these in
        # so they are read once and not per row.
        running_uuids = kwargs.get('running_uuids')
        if running_uuids is None:
            running_uuids = worker_pool.get_running_uuids()

        queue_list = kwargs.get('queued_uuids')
        if queue_list is None:
            queue_list = update_q.get_queued_uuids()

        watch_data = {
            'checking_now': True if watch.get('uuid') in running_uuids else False,
            'event_timestamp': time.time(),
            'notification_muted': True if watch.get('notification_muted') else False,
            'paused': True if watch.get('paused') else False,
            'queued': True if watch.get('uuid') in queue_list else False,
            'uuid': watch.get('uuid'),
        }

        socketio.emit("watch_update", {'watch': watch_data}, to=watch_room(watch_data['uuid']))

        # And the row itself for the watch list, which shows it as the server draws it
        if kwargs.get('datastore') is not None:
            send_watch_list_row(socketio, watch, kwargs['datastore'], queued_uuids=queue_list)

        # Log after successful emit - use watch_data['uuid'] to avoid variable shadowing issues
        logger.trace(f"Socket.IO: Emitted update for watch {watch_data['uuid']}, Checking now: {watch_data['checking_now']}")

    except Exception as e:
        logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


def _suppress_werkzeug_ws_abrupt_disconnect_noise():
    """Patch BaseWSGIServer.log to suppress the AssertionError traceback that fires when
    a browser closes a WebSocket connection mid-handshake (e.g. closing a tab).
    The exception is caught inside run_wsgi and routed to self.server.log() — it never
    propagates out, so wrapping run_wsgi doesn't help. Patching the log method is the
    only reliable intercept point. The error is cosmetic: Socket.IO already handles the
    disconnect correctly via its own disconnect handler and timeout logic."""
    try:
        from werkzeug.serving import BaseWSGIServer
        _original_log = BaseWSGIServer.log

        def _filtered_log(self, type, message, *args):
            if type == 'error' and 'write() before start_response' in message:
                return
            _original_log(self, type, message, *args)

        BaseWSGIServer.log = _filtered_log
    except Exception:
        pass


def init_socketio(app, datastore):
    """Initialize SocketIO with the main Flask app"""
    _suppress_werkzeug_ws_abrupt_disconnect_noise()

    import platform
    import sys

    # Platform-specific async_mode selection for better stability
    system = platform.system().lower()
    python_version = sys.version_info

    # Check for SocketIO mode configuration via environment variable
    # Default is 'threading' for best cross-platform compatibility
    socketio_mode = os.getenv('SOCKETIO_MODE', 'threading').lower()

    if socketio_mode == 'gevent':
        # Use gevent mode (higher concurrency but platform limitations)
        try:
            import gevent
            async_mode = 'gevent'
            logger.info(f"SOCKETIO_MODE=gevent: Using {async_mode} mode for Socket.IO")
        except ImportError:
            async_mode = 'threading'
            logger.warning(f"SOCKETIO_MODE=gevent but gevent not available, falling back to {async_mode} mode")
    elif socketio_mode == 'threading':
        # Use threading mode (default - best compatibility)
        async_mode = 'threading'
        logger.info(f"SOCKETIO_MODE=threading: Using {async_mode} mode for Socket.IO")
    else:
        # Invalid mode specified, use default
        async_mode = 'threading'
        logger.warning(f"Invalid SOCKETIO_MODE='{socketio_mode}', using default {async_mode} mode for Socket.IO")

    # Log platform info for debugging
    logger.info(f"Platform: {system}, Python: {python_version.major}.{python_version.minor}, Socket.IO mode: {async_mode}")

    # Restrict SocketIO CORS to same origin by default, can be overridden with env var
    cors_origins = os.environ.get('SOCKETIO_CORS_ORIGINS', None)

    socketio = SocketIO(app,
                        async_mode=async_mode,
                        cors_allowed_origins=cors_origins,  # None means same-origin only
                        logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')),
                        engineio_logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')),
                        # Disable WebSocket compression to prevent memory accumulation
                        # Flask-Compress already handles HTTP response compression
                        engineio_options={'http_compression': False, 'compression_threshold': 0},
                        # A bulk operation sends the selected UUIDs in one message, about 40 bytes each. The
                        # default of 1MB drops the connection at around 25,000 selected.
                        max_http_buffer_size=MAX_SOCKET_MESSAGE_BYTES)

    # Set up event handlers
    logger.info("Socket.IO: Registering connect event handler")

    @socketio.on('checkbox-operation')
    @login_optionally_required_for_event(datastore)
    def event_checkbox_operations(data):
        from changedetectionio.blueprint.ui import _handle_operations
        from changedetectionio import queuedWatchMetaData
        from changedetectionio import worker_pool
        from changedetectionio.flask_app import update_q, watch_check_update
        import threading

        logger.trace(f"Got checkbox operations event: {data}")

        datastore = socketio.datastore
        # Capture the requesting client's session id now (request context is gone inside the thread)
        # so we can send the feedback toast only back to them, not broadcast to everyone.
        from flask import request
        sid = getattr(request, 'sid', None)

        def run_operation():
            """Run the operation in a background thread to avoid blocking the socket.io event loop"""
            try:
                result = _handle_operations(
                    op=data.get('op'),
                    uuids=data.get('uuids'),
                    datastore=datastore,
                    extra_data=data.get('extra_data'),
                    worker_pool=worker_pool,
                    update_q=update_q,
                    queuedWatchMetaData=queuedWatchMetaData,
                    watch_check_update=watch_check_update,
                    emit_flash=False
                )
                # Server-driven feedback: tell the requesting client what happened (real count / errors)
                if result and result.get('message') and sid:
                    socketio.emit('toast', {'message': result['message'], 'type': result.get('type', 'success')}, to=sid)
            except Exception as e:
                logger.error(f"Error in checkbox operation thread: {e}")

        # Start operation in a disposable daemon thread
        thread = threading.Thread(target=run_operation, daemon=True, name=f"checkbox-op-{data.get('op')}")
        thread.start()

    @socketio.on('watch-subscribe')
    @login_optionally_required_for_event(datastore)
    def event_watch_subscribe(data):
        """The page lists the watches it is showing, from then on it gets the per-watch events for those only."""
        from flask_socketio import join_room

        uuids = (data or {}).get('uuids')
        if not isinstance(uuids, list):
            return
        watching = socketio.datastore.data['watching']
        # A watch list says which group it is filtered by and gets the rendered rows for that, see watch_row_room()
        rows_for = (data or {}).get('rows_for_tag')
        if rows_for is not None and not (isinstance(rows_for, str) and (rows_for == '' or rows_for in socketio.datastore.data['settings']['application']['tags'])):
            rows_for = None
        url_prefix = connection_url_prefix() if rows_for is not None else ''
        for uuid in uuids[:MAX_WATCH_SUBSCRIPTIONS]:
            if isinstance(uuid, str) and uuid in watching:
                join_room(watch_room(uuid))
                if rows_for is not None:
                    join_room(watch_row_room(uuid, rows_for, url_prefix))
                    _row_filters_shown.setdefault(uuid, set()).add((rows_for, url_prefix))

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        #        logger.info("Socket.IO: CONNECT HANDLER CALLED - Starting connection process")
        from flask import request
        from changedetectionio.flask_app import update_q
        from changedetectionio import worker_pool

        # Access datastore from socketio
        datastore = socketio.datastore
        #        logger.info(f"Socket.IO: Current user authenticated: {current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else 'No current_user'}")

        if not socket_client_is_allowed(datastore):
            logger.warning("Socket.IO: Rejecting unauthenticated connection")
            return False  # Reject the connection

        # Send the current queue size to the newly connected client
        try:
            queue_size = update_q.qsize()
            socketio.emit("queue_size", {
                "q_length": queue_size,
                "event_timestamp": time.time()
            }, room=request.sid)  # Send only to this client
            logger.debug(f"Socket.IO: Sent initial queue size {queue_size} to new client")

            # Send the current "checking now" count (how many watches workers are processing right now)
            checking_now = len(worker_pool.get_running_uuids())
            socketio.emit("checking_now", {
                "count": checking_now,
                "event_timestamp": time.time()
            }, room=request.sid)  # Send only to this client
            logger.debug(f"Socket.IO: Sent initial checking_now {checking_now} to new client")
        except Exception as e:
            logger.error(f"Socket.IO error sending initial queue size: {str(e)}")

        logger.info("Socket.IO: Client connected")

    #    logger.info("Socket.IO: Registering disconnect event handler")
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info("Socket.IO: Client disconnected")

    # Create a dedicated signal handler that will receive signals and emit them to clients
    signal_handler = SignalHandler(socketio, datastore)

    # Register watch operation event handlers
    from .events import register_watch_operation_handlers
    register_watch_operation_handlers(socketio, datastore)

    # Store the datastore reference on the socketio object for later use
    socketio.datastore = datastore

    # No stop event needed for threading mode - threads check app.config.exit directly

    # Add a shutdown method to the socketio object
    def shutdown():
        """Shutdown the SocketIO server fast and aggressively"""
        try:
            logger.info("Socket.IO: Fast shutdown initiated...")
            logger.info("Socket.IO: Fast shutdown complete")
        except Exception as e:
            logger.error(f"Socket.IO error during shutdown: {str(e)}")

    # Attach the shutdown method to the socketio object
    socketio.shutdown = shutdown

    logger.info("Socket.IO initialized and attached to main Flask app")
    logger.info(f"Socket.IO: Registered event handlers: {socketio.handlers if hasattr(socketio, 'handlers') else 'No handlers found'}")
    return socketio
