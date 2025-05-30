import timeago
from flask_socketio import SocketIO

import time
import os
from loguru import logger
from blinker import signal

from changedetectionio import strtobool


class SignalHandler:
    """A standalone class to receive signals"""

    def __init__(self, socketio_instance, datastore):
        self.socketio_instance = socketio_instance
        self.datastore = datastore

        # Connect to the watch_check_update signal
        from changedetectionio.flask_app import watch_check_update as wcc
        wcc.connect(self.handle_signal, weak=False)
        #        logger.info("SignalHandler: Connected to signal from direct import")

        # Connect to the queue_length signal
        queue_length_signal = signal('queue_length')
        queue_length_signal.connect(self.handle_queue_length, weak=False)
        #       logger.info("SignalHandler: Connected to queue_length signal")

        # Create and start the queue update thread using eventlet
        import eventlet
        self.polling_emitter_thread = eventlet.spawn(self.polling_emit_running_or_queued_watches)

        # Store the thread reference in socketio for clean shutdown
        self.socketio_instance.polling_emitter_thread = self.polling_emitter_thread

    def handle_signal(self, *args, **kwargs):
        logger.trace(f"SignalHandler: Signal received with {len(args)} args and {len(kwargs)} kwargs")
        # Safely extract the watch UUID from kwargs
        watch_uuid = kwargs.get('watch_uuid')
        app_context = kwargs.get('app_context')

        if watch_uuid:
            # Get the watch object from the datastore
            watch = self.datastore.data['watching'].get(watch_uuid)
            if watch:
                if app_context:
                    # note
                    with app_context.app_context():
                        with app_context.test_request_context():
                            # Forward to handle_watch_update with the watch parameter
                            handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore)
                else:
                    handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore)

                logger.trace(f"Signal handler processed watch UUID {watch_uuid}")
            else:
                logger.warning(f"Watch UUID {watch_uuid} not found in datastore")

    def handle_queue_length(self, *args, **kwargs):
        """Handle queue_length signal and emit to all clients"""
        try:
            queue_length = kwargs.get('length', 0)
            logger.debug(f"SignalHandler: Queue length update received: {queue_length}")

            # Emit the queue size to all connected clients
            self.socketio_instance.emit("queue_size", {
                "q_length": queue_length,
                "event_timestamp": time.time()
            })

        except Exception as e:
            logger.error(f"Socket.IO error in handle_queue_length: {str(e)}")

    def polling_emit_running_or_queued_watches(self):
        """Greenlet that periodically updates the browser/frontend with current state of who is being checked or queued
        This is because sometimes the browser page could reload (like on clicking on a link) but the data is old
        """
        logger.info("Queue update eventlet greenlet started")

        # Import the watch_check_update signal, update_q, and worker_handler here to avoid circular imports
        from changedetectionio.flask_app import app
        from changedetectionio import worker_handler
        watch_check_update = signal('watch_check_update')

        # Use eventlet sleep for non-blocking operation
        from eventlet import sleep as eventlet_sleep

        # Get the stop event from the socketio instance
        stop_event = self.socketio_instance.stop_event if hasattr(self.socketio_instance, 'stop_event') else None

        # Run until explicitly stopped
        while stop_event is None or not stop_event.ready():
            try:
                # Get current running UUIDs from async workers
                running_uuids = set(worker_handler.get_running_uuids())

                # Send updates for newly running UUIDs
                with app.app_context():
                    for uuid in running_uuids:
                        watch_check_update.send(app_context=app, watch_uuid=uuid)
                    eventlet_sleep(0.01)  # Small yield

            except Exception as e:
                logger.error(f"Error in queue update greenlet: {str(e)}")
                # Sleep a bit to avoid flooding logs in case of persistent error
                eventlet_sleep(0.5)

            eventlet_sleep(10)

        logger.info("Queue update eventlet greenlet stopped")


def handle_watch_update(socketio, **kwargs):
    """Handle watch update signal from blinker"""
    try:
        watch = kwargs.get('watch')
        datastore = kwargs.get('datastore')

        # Emit the watch update to all connected clients
        from changedetectionio.flask_app import update_q
        from changedetectionio.flask_app import _jinja2_filter_datetime
        from changedetectionio import worker_handler

        # Get list of watches that are currently running
        running_uuids = worker_handler.get_running_uuids()

        # Get list of watches in the queue
        queue_list = []
        for q_item in update_q.queue:
            if hasattr(q_item, 'item') and 'uuid' in q_item.item:
                queue_list.append(q_item.item['uuid'])

        error_texts = ""
        # Get the error texts from the watch
        error_texts = watch.compile_error_texts()

        # Create a simplified watch data object to send to clients
        watch_uuid = watch.get('uuid')
        
        watch_data = {
            'checking_now': True if watch_uuid in running_uuids else False,
            'fetch_time': watch.get('fetch_time'),
            'has_error': True if error_texts else False,
            'last_changed': watch.get('last_changed'),
            'last_checked': watch.get('last_checked'),
            'error_text': error_texts,
            'last_checked_text': _jinja2_filter_datetime(watch),
            'last_changed_text': timeago.format(int(watch['last_changed']), time.time()) if watch.history_n >= 2 and int(
                watch.get('last_changed', 0)) > 0 else 'Not yet',
            'queued': True if watch_uuid in queue_list else False,
            'paused': True if watch.get('paused') else False,
            'notification_muted': True if watch.get('notification_muted') else False,
            'unviewed': watch.has_unviewed,
            'uuid': watch_uuid,
            'event_timestamp': time.time()
        }

        errored_count = 0
        for watch_uuid_iter, watch_iter in datastore.data['watching'].items():
            if watch_iter.get('last_error'):
                errored_count += 1

        general_stats = {
            'count_errors': errored_count,
            'has_unviewed': datastore.has_unviewed
        }

        # Debug what's being emitted
        # logger.debug(f"Emitting 'watch_update' event for {watch.get('uuid')}, data: {watch_data}")

        # Emit to all clients (no 'broadcast' parameter needed - it's the default behavior)
        socketio.emit("watch_update", {'watch': watch_data, 'general_stats': general_stats})

        # Log after successful emit - use watch_data['uuid'] to avoid variable shadowing issues
        logger.trace(f"Socket.IO: Emitted update for watch {watch_data['uuid']}, Checking now: {watch_data['checking_now']}")

    except Exception as e:
        logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


def init_socketio(app, datastore):
    """Initialize SocketIO with the main Flask app"""
    # Use eventlet async_mode now that Playwright is async and compatible
    # Eventlet mode works well with async_playwright
    async_mode = 'eventlet'
    logger.info(f"Using {async_mode} mode for Socket.IO")

    # Restrict SocketIO CORS to same origin by default, can be overridden with env var
    cors_origins = os.environ.get('SOCKETIO_CORS_ORIGINS', None)

    socketio = SocketIO(app,
                        async_mode=async_mode,
                        cors_allowed_origins=cors_origins,  # None means same-origin only
                        logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')),
                        engineio_logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')))

    # Set up event handlers
    logger.info("Socket.IO: Registering connect event handler")

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        #        logger.info("Socket.IO: CONNECT HANDLER CALLED - Starting connection process")
        from flask import request
        from flask_login import current_user
        from changedetectionio.flask_app import update_q

        # Access datastore from socketio
        datastore = socketio.datastore
        #        logger.info(f"Socket.IO: Current user authenticated: {current_user.is_authenticated if hasattr(current_user, 'is_authenticated') else 'No current_user'}")

        # Check if authentication is required and user is not authenticated
        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)
        #        logger.info(f"Socket.IO: Password enabled: {has_password_enabled}")
        if has_password_enabled and not current_user.is_authenticated:
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

    # Create a stop event for our queue update thread using eventlet Event
    import eventlet.event
    stop_event = eventlet.event.Event()
    socketio.stop_event = stop_event

    # Add a shutdown method to the socketio object
    def shutdown():
        """Shutdown the SocketIO server gracefully"""
        try:
            logger.info("Socket.IO: Shutting down server...")

            # Signal the queue update thread to stop
            if hasattr(socketio, 'stop_event'):
                socketio.stop_event.send()
                logger.info("Socket.IO: Signaled queue update thread to stop")

            # Wait for the greenlet to exit (with timeout)
            if hasattr(socketio, 'polling_emitter_thread'):
                try:
                    # For eventlet greenlets - just kill it directly to avoid MAINLOOP issues
                    if not socketio.polling_emitter_thread.dead:
                        socketio.polling_emitter_thread.kill()
                        logger.info("Socket.IO: Queue update eventlet greenlet killed")
                    else:
                        logger.info("Socket.IO: Queue update eventlet greenlet already dead")
                except Exception as e:
                    logger.error(f"Error killing eventlet greenlet: {str(e)}")

            # Close any remaining client connections
            # if hasattr(socketio, 'server'):
            #    socketio.server.disconnect()
            logger.info("Socket.IO: Server shutdown complete")
        except Exception as e:
            logger.error(f"Socket.IO error during shutdown: {str(e)}")

    # Attach the shutdown method to the socketio object
    socketio.shutdown = shutdown

    logger.info("Socket.IO initialized and attached to main Flask app")
    logger.info(f"Socket.IO: Registered event handlers: {socketio.handlers if hasattr(socketio, 'handlers') else 'No handlers found'}")
    return socketio
