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

        watch_delete_signal = signal('watch_deleted')
        watch_delete_signal.connect(self.handle_deleted_signal, weak=False)

        # Create and start the queue update thread using standard threading
        import threading
        self.polling_emitter_thread = threading.Thread(
            target=self.polling_emit_running_or_queued_watches_threaded, 
            daemon=True
        )
        self.polling_emitter_thread.start()
        logger.info("Started polling thread using threading (eventlet-free)")

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


    def polling_emit_running_or_queued_watches_threaded(self):
        """Threading version of polling for Windows compatibility"""
        import time
        import threading
        logger.info("Queue update thread started (threading mode)")
        
        # Import here to avoid circular imports
        from changedetectionio.flask_app import app
        from changedetectionio import worker_handler
        watch_check_update = signal('watch_check_update')
        
        # Track previous state to avoid unnecessary emissions
        previous_running_uuids = set()
        
        # Run until app shutdown - check exit flag more frequently for fast shutdown
        exit_event = getattr(app.config, 'exit', threading.Event())
        
        while not exit_event.is_set():
            try:
                # Get current running UUIDs from async workers
                running_uuids = set(worker_handler.get_running_uuids())
                
                # Only send updates for UUIDs that changed state
                newly_running = running_uuids - previous_running_uuids
                no_longer_running = previous_running_uuids - running_uuids
                
                # Send updates for newly running UUIDs (but exit fast if shutdown requested)
                for uuid in newly_running:
                    if exit_event.is_set():
                        break
                    logger.trace(f"Threading polling: UUID {uuid} started processing")
                    with app.app_context():
                        watch_check_update.send(app_context=app, watch_uuid=uuid)
                    time.sleep(0.01)  # Small yield
                
                # Send updates for UUIDs that finished processing (but exit fast if shutdown requested)
                if not exit_event.is_set():
                    for uuid in no_longer_running:
                        if exit_event.is_set():
                            break
                        logger.trace(f"Threading polling: UUID {uuid} finished processing")
                        with app.app_context():
                            watch_check_update.send(app_context=app, watch_uuid=uuid)
                        time.sleep(0.01)  # Small yield
                
                # Update tracking for next iteration
                previous_running_uuids = running_uuids
                
                # Sleep between polling cycles, but check exit flag every 0.5 seconds for fast shutdown
                for _ in range(20):  # 20 * 0.5 = 10 seconds total
                    if exit_event.is_set():
                        break
                    time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error in threading polling: {str(e)}")
                # Even during error recovery, check for exit quickly
                for _ in range(1):  # 1 * 0.5 = 0.5 seconds
                    if exit_event.is_set():
                        break
                    time.sleep(0.5)
        
        # Check if we're in pytest environment - if so, be more gentle with logging
        import sys
        in_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
        
        if not in_pytest:
            logger.info("Queue update thread stopped (threading mode)")


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

        # Get the error texts from the watch
        error_texts = watch.compile_error_texts()
        # Create a simplified watch data object to send to clients

        watch_data = {
            'checking_now': True if watch.get('uuid') in running_uuids else False,
            'fetch_time': watch.get('fetch_time'),
            'has_error': True if error_texts else False,
            'last_changed': watch.get('last_changed'),
            'last_checked': watch.get('last_checked'),
            'error_text': error_texts,
            'history_n': watch.history_n,
            'last_checked_text': _jinja2_filter_datetime(watch),
            'last_changed_text': timeago.format(int(watch.last_changed), time.time()) if watch.history_n >= 2 and int(watch.last_changed) > 0 else 'Not yet',
            'queued': True if watch.get('uuid') in queue_list else False,
            'paused': True if watch.get('paused') else False,
            'notification_muted': True if watch.get('notification_muted') else False,
            'unviewed': watch.has_unviewed,
            'uuid': watch.get('uuid'),
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
                        engineio_logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')))

    # Set up event handlers
    logger.info("Socket.IO: Registering connect event handler")

    @socketio.on('checkbox-operation')
    def event_checkbox_operations(data):
        from changedetectionio.blueprint.ui import _handle_operations
        from changedetectionio import queuedWatchMetaData
        from changedetectionio import worker_handler
        from changedetectionio.flask_app import update_q, watch_check_update
        logger.trace(f"Got checkbox operations event: {data}")

        datastore = socketio.datastore

        _handle_operations(
            op=data.get('op'),
            uuids=data.get('uuids'),
            datastore=datastore,
            extra_data=data.get('extra_data'),
            worker_handler=worker_handler,
            update_q=update_q,
            queuedWatchMetaData=queuedWatchMetaData,
            watch_check_update=watch_check_update,
            emit_flash=False
        )


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

    # No stop event needed for threading mode - threads check app.config.exit directly

    # Add a shutdown method to the socketio object
    def shutdown():
        """Shutdown the SocketIO server fast and aggressively"""
        try:
            logger.info("Socket.IO: Fast shutdown initiated...")

            # For threading mode, give the thread a very short time to exit gracefully
            if hasattr(socketio, 'polling_emitter_thread'):
                if socketio.polling_emitter_thread.is_alive():
                    logger.info("Socket.IO: Waiting 1 second for polling thread to stop...")
                    socketio.polling_emitter_thread.join(timeout=1.0)  # Only 1 second timeout
                    if socketio.polling_emitter_thread.is_alive():
                        logger.info("Socket.IO: Polling thread still running after timeout - continuing with shutdown")
                    else:
                        logger.info("Socket.IO: Polling thread stopped quickly")
                else:
                    logger.info("Socket.IO: Polling thread already stopped")

            logger.info("Socket.IO: Fast shutdown complete")
        except Exception as e:
            logger.error(f"Socket.IO error during shutdown: {str(e)}")

    # Attach the shutdown method to the socketio object
    socketio.shutdown = shutdown

    logger.info("Socket.IO initialized and attached to main Flask app")
    logger.info(f"Socket.IO: Registered event handlers: {socketio.handlers if hasattr(socketio, 'handlers') else 'No handlers found'}")
    return socketio
