import timeago
from flask_socketio import SocketIO

import time
import os
import threading
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

    def handle_signal(self, *args, **kwargs):
        logger.info(f"SignalHandler: Signal received with {len(args)} args and {len(kwargs)} kwargs")
        # Safely extract the watch UUID from kwargs
        watch_uuid = kwargs.get('watch_uuid')
        if watch_uuid:
            # Get the watch object from the datastore
            watch = self.datastore.data['watching'].get(watch_uuid)
            if watch:
                # Forward to handle_watch_update with the watch parameter
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

        # Create a simplified watch data object to send to clients
        last_error_text = ' - '.join(filter(None, [watch.get('last_notification_error', ''), watch.get('error_text', '')])).strip()
        watch_data = {
            'checking_now': True if watch.get('uuid') in running_uuids else False,
            'fetch_time': watch.get('fetch_time'),
            'has_error': True if watch.get('last_error') or watch.get('last_notification_error') else False,
            'last_changed': watch.get('last_changed'),
            'last_checked': watch.get('last_checked'),
            'error_text': last_error_text,
            'last_checked_text': _jinja2_filter_datetime(watch),
            'last_changed_text': timeago.format(int(watch['last_changed']), time.time()) if watch.history_n >= 2 and int(watch.get('last_changed', 0)) > 0 else 'Not yet',
            'queued': True if watch.get('uuid') in queue_list else False,
            'paused': True if watch.get('paused') else False,
            'notification_muted': True if watch.get('notification_muted') else False,
            'unviewed': watch.has_unviewed,
            'uuid': watch.get('uuid'),
            'event_timestamp': time.time()
        }
        socketio.emit("watch_update", watch_data)
        logger.debug(f"Socket.IO: Emitted update for watch {watch.get('uuid')}, Checking now: {watch_data['checking_now']}")

    except Exception as e:
        logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


def queue_update_thread(socketio, stop_event):
    """Thread that periodically sends updates for watches in the queue"""
    logger.info("Queue update thread started")
    
    # Import the watch_check_update signal and update_q here to avoid circular imports
    from changedetectionio.flask_app import watch_check_update, update_q
    
    while not stop_event.is_set():
        try:
            # For each item in the queue, send a signal
            for q_item in update_q.queue:
                if hasattr(q_item, 'item') and 'uuid' in q_item.item:
                    # Send the signal with the watch_uuid parameter
                    watch_check_update.send(watch_uuid=q_item.item['uuid'])
                    logger.debug(f"Queue update thread: Sent update for watch {q_item.item['uuid']}")
            
            # Sleep for 3 seconds checking every 0.1 to quit
            for _ in range(30):  # Check stop_event every 0.1 seconds for 3 seconds total
                if stop_event.is_set():
                    break
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error in queue update thread: {str(e)}")
            # Sleep a bit to avoid flooding logs in case of persistent error
            time.sleep(0.5)
    
    logger.info("Queue update thread stopped")

def init_socketio(app, datastore):
    """Initialize SocketIO with the main Flask app"""
    # Use the threading async_mode instead of eventlet
    # This avoids the need for monkey patching eventlet,
    # Which leads to problems with async playwright etc
    async_mode = 'threading'
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
    
    # Create a stop event for our queue update thread
    stop_event = threading.Event()
    socketio.stop_event = stop_event
    
    # Create and start the queue update thread
    queue_thread = threading.Thread(
        target=queue_update_thread,
        args=(socketio, stop_event),
        daemon=True,
        name="QueueUpdateThread"
    )
    socketio.queue_thread = queue_thread
    queue_thread.start()
    logger.info("Queue update thread initialized")
    
    # Add a shutdown method to the socketio object
    def shutdown():
        """Shutdown the SocketIO server gracefully"""
        try:
            logger.info("Socket.IO: Shutting down server...")
            
            # Signal the queue update thread to stop
            if hasattr(socketio, 'stop_event'):
                socketio.stop_event.set()
                logger.info("Socket.IO: Signaled queue update thread to stop")
            
            # Wait for the thread to exit (with timeout)
            if hasattr(socketio, 'queue_thread') and socketio.queue_thread.is_alive():
                socketio.queue_thread.join(timeout=5.0)
                logger.info("Socket.IO: Queue update thread joined" if not socketio.queue_thread.is_alive() 
                           else "Socket.IO: Queue update thread did not exit in time")
            
            # Close any remaining client connections
            if hasattr(socketio, 'server'):
                socketio.server.disconnect()
            logger.info("Socket.IO: Server shutdown complete")
        except Exception as e:
            logger.error(f"Socket.IO error during shutdown: {str(e)}")
    
    # Attach the shutdown method to the socketio object
    socketio.shutdown = shutdown

    logger.info("Socket.IO initialized and attached to main Flask app")
    return socketio
