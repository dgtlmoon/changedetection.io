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
        logger.info("SignalHandler: Connected to signal from direct import")
        
        # Connect to the queue_length signal
        queue_length_signal = signal('queue_length')
        queue_length_signal.connect(self.handle_queue_length, weak=False)
        logger.info("SignalHandler: Connected to queue_length signal")


        # Create and start the queue update thread using gevent
        import gevent
        logger.info("Using gevent for polling thread")
        self.polling_emitter_thread = gevent.spawn(self.polling_emit_running_or_queued_watches)
        
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
                    #note
                    with app_context.app_context():
                        with app_context.test_request_context():
                            # Forward to handle_watch_update with the watch parameter
                            handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore)
                else:
                    handle_watch_update(self.socketio_instance, watch=watch, datastore=self.datastore)

                logger.info(f"Signal handler processed watch UUID {watch_uuid}")
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
        logger.info("Queue update greenlet started")

        # Import the watch_check_update signal, update_q, and running_update_threads here to avoid circular imports
        from changedetectionio.flask_app import app, running_update_threads
        watch_check_update = signal('watch_check_update')
        
        # Use gevent sleep for non-blocking operation
        from gevent import sleep as gevent_sleep

        # Get the stop event from the socketio instance
        stop_event = self.socketio_instance.stop_event if hasattr(self.socketio_instance, 'stop_event') else None

        # Run until explicitly stopped
        while stop_event is None or not stop_event.is_set():
            try:
                # For each item in the queue, send a signal, so we update the UI
                for t in running_update_threads:
                    if hasattr(t, 'current_uuid') and t.current_uuid:
                        logger.debug(f"Sending update for {t.current_uuid}")
                        # Send with app_context to ensure proper URL generation
                        with app.app_context():
                            watch_check_update.send(app_context=app, watch_uuid=t.current_uuid)
                        # Yield control back to gevent after each send to prevent blocking
                        gevent_sleep(0.1)  # Small sleep to yield control
                    
                    # Check if we need to stop in the middle of processing
                    if stop_event is not None and stop_event.is_set():
                        break

                # Sleep between polling/update cycles
                gevent_sleep(2)

            except Exception as e:
                logger.error(f"Error in queue update greenlet: {str(e)}")
                # Sleep a bit to avoid flooding logs in case of persistent error
                gevent_sleep(0.5)

        logger.info("Queue update greenlet stopped")


def handle_watch_update(socketio, **kwargs):
    """Handle watch update signal from blinker"""
    try:
        watch = kwargs.get('watch')
        datastore = kwargs.get('datastore')

        # Emit the watch update to all connected clients
        from changedetectionio.flask_app import running_update_threads, update_q
        from changedetectionio.flask_app import _jinja2_filter_datetime

        # Get list of watches that are currently running
        running_uuids = []
        for t in running_update_threads:
            if hasattr(t, 'current_uuid') and t.current_uuid:
                running_uuids.append(t.current_uuid)

        # Get list of watches in the queue
        queue_list = []
        for q_item in update_q.queue:
            if hasattr(q_item, 'item') and 'uuid' in q_item.item:
                queue_list.append(q_item.item['uuid'])

        error_texts = ""
        # Get the error texts from the watch
        error_texts = watch.compile_error_texts()

        # Create a simplified watch data object to send to clients
        watch_data = {
            'checking_now': True if watch.get('uuid') in running_uuids else False,
            'error_text': error_texts,
            'event_timestamp': time.time(),
            'fetch_time': watch.get('fetch_time'),
            'has_error': True if error_texts else False,
            'has_thumbnail': True if watch.get_screenshot_as_thumbnail() else False,
            'last_changed': watch.get('last_changed'),
            'last_changed_text': timeago.format(int(watch['last_changed']), time.time()) if watch.history_n >= 2 and int(watch.get('last_changed', 0)) > 0 else 'Not yet',
            'last_checked': watch.get('last_checked'),
            'last_checked_text': _jinja2_filter_datetime(watch),
            'notification_muted': True if watch.get('notification_muted') else False,
            'paused': True if watch.get('paused') else False,
            'queued': True if watch.get('uuid') in queue_list else False,
            'unviewed': watch.has_unviewed,
            'uuid': watch.get('uuid'),
        }

        errored_count =0
        for uuid, watch in datastore.data['watching'].items():
            if watch.get('last_error'):
                errored_count += 1

        general_stats = {
            'count_errors': errored_count,
            'has_unviewed': datastore.has_unviewed
        }

        # Debug what's being emitted
        #logger.debug(f"Emitting 'watch_update' event for {watch.get('uuid')}, data: {watch_data}")
        
        # Emit to all clients (no 'broadcast' parameter needed - it's the default behavior)
        socketio.emit("watch_update", {'watch': watch_data, 'general_stats': general_stats})
        
        # Log after successful emit
        #logger.info(f"Socket.IO: Emitted update for watch {watch.get('uuid')}, Checking now: {watch_data['checking_now']}")

    except Exception as e:
        logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


def init_socketio(app, datastore):
    """Initialize SocketIO with the main Flask app"""
    # Use the threading async_mode instead of eventlet
    # This avoids the need for monkey patching eventlet,
    # Which leads to problems with async playwright etc
    async_mode = 'gevent'
    logger.info(f"Using {async_mode} mode for Socket.IO")

    # Restrict SocketIO CORS to same origin by default, can be overridden with env var
    cors_origins = os.environ.get('SOCKETIO_CORS_ORIGINS', None)
    
    socketio = SocketIO(app,
                      async_mode=async_mode,
                      cors_allowed_origins=cors_origins,  # None means same-origin only
                      logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')),
                      engineio_logger=strtobool(os.getenv('SOCKETIO_LOGGING', 'False')))

    # Set up event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        from changedetectionio.auth_decorator import login_optionally_required
        from flask import request
        from flask_login import current_user
        from changedetectionio.flask_app import update_q

        # Access datastore from socketio
        datastore = socketio.datastore

        # Check if authentication is required and user is not authenticated
        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)
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

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info("Socket.IO: Client disconnected")

    # Create a dedicated signal handler that will receive signals and emit them to clients
    signal_handler = SignalHandler(socketio, datastore)

    # Store the datastore reference on the socketio object for later use
    socketio.datastore = datastore
    
    # Create a stop event for our queue update thread using gevent Event
    import gevent.event
    stop_event = gevent.event.Event()
    socketio.stop_event = stop_event

    
    # Add a shutdown method to the socketio object
    def shutdown():
        """Shutdown the SocketIO server gracefully"""
        try:
            logger.info("Socket.IO: Shutting down server...")
            
            # Signal the queue update thread to stop
            if hasattr(socketio, 'stop_event'):
                socketio.stop_event.set()
                logger.info("Socket.IO: Signaled queue update thread to stop")
            
            # Wait for the greenlet to exit (with timeout)
            if hasattr(socketio, 'polling_emitter_thread'):
                try:
                    # For gevent greenlets
                    socketio.polling_emitter_thread.join(timeout=5)
                    logger.info("Socket.IO: Queue update greenlet joined successfully")
                except Exception as e:
                    logger.error(f"Error joining greenlet: {str(e)}")
                    logger.info("Socket.IO: Queue update greenlet did not exit in time")
            
            # Close any remaining client connections
            #if hasattr(socketio, 'server'):
            #    socketio.server.disconnect()
            logger.info("Socket.IO: Server shutdown complete")
        except Exception as e:
            logger.error(f"Socket.IO error during shutdown: {str(e)}")
    
    # Attach the shutdown method to the socketio object
    socketio.shutdown = shutdown

    logger.info("Socket.IO initialized and attached to main Flask app")
    return socketio
