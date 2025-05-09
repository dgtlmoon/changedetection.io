import timeago
from flask import Flask
from flask_socketio import SocketIO
import threading
import json
import time
from loguru import logger
import blinker

from changedetectionio.flask_app import _jinja2_filter_datetime, watch_check_completed


class SignalHandler:
    """A standalone class to receive signals"""
    def __init__(self, socketio_instance):
        self.socketio_instance = socketio_instance
        
        # Get signal from app config
        app_signal = socketio_instance.main_app.config.get('WATCH_CHECK_COMPLETED_SIGNAL')
        if app_signal:
            app_signal.connect(self.handle_signal, weak=False)
            logger.info("SignalHandler: Connected to signal from app config")
        else:
            # Fallback if not in app config
            from changedetectionio.flask_app import watch_check_completed as wcc
            wcc.connect(self.handle_signal, weak=False)
            logger.info("SignalHandler: Connected to signal from direct import")
    
    def handle_signal(self, *args, **kwargs):
        logger.info(f"SignalHandler: Signal received with {len(args)} args and {len(kwargs)} kwargs")
        # Safely extract the watch UUID from kwargs
        watch_uuid = kwargs.get('watch_uuid')
        if watch_uuid:
            # Get the datastore from the socket instance
            datastore = self.socketio_instance.datastore
            # Get the watch object from the datastore
            watch = datastore.data['watching'].get(watch_uuid)
            if watch:
                # Forward to the socket instance with the watch parameter
                self.socketio_instance.handle_watch_update(watch=watch)
                logger.info(f"Signal handler processed watch UUID {watch_uuid}")
            else:
                logger.warning(f"Watch UUID {watch_uuid} not found in datastore")

class ChangeDetectionSocketIO:
    def __init__(self, app, datastore):
        self.main_app = app
        self.datastore = datastore

        # Use threading mode instead of eventlet
        self.socketio = SocketIO(self.main_app,
                                async_mode='threading', 
                                cors_allowed_origins="*",
                                logger=False,
                                engineio_logger=False)
        
        # Set up event handlers
        self.socketio.on_event('connect', self.handle_connect)
        self.socketio.on_event('disconnect', self.handle_disconnect)
        
        # Don't patch the update_watch method - this was causing issues
        # Just start a background thread to periodically emit watch status
        self.thread = None
        self.thread_lock = threading.Lock()
        
        # Create a dedicated signal handler
        self.signal_handler = SignalHandler(self)

    def handle_connect(self):
        """Handle client connection"""
        logger.info("Socket.IO: Client connected")
        

    def handle_disconnect(self):
        """Handle client disconnection"""
        logger.info("Socket.IO: Client disconnected")
    
    def handle_watch_update(self, **kwargs):
        """Handle watch update signal from blinker"""
        try:
            watch = kwargs.get('watch')
            # Emit the watch update to all connected clients
            with self.main_app.app_context():
                from changedetectionio.flask_app import running_update_threads, update_q

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
                watch_data = {
                    'checking_now': True if watch.get('uuid') in running_uuids else False,
                    'fetch_time': watch.get('fetch_time'),
                    'has_error': watch.get('last_error') or watch.get('last_notification_error'),
                    'last_changed': watch.get('last_changed'),
                    'last_checked': watch.get('last_checked'),
                    'last_checked_text': _jinja2_filter_datetime(watch),
                    'last_changed_text': timeago.format(int(watch['last_changed']), time.time()) if watch.history_n >=2 and int(watch.get('last_changed',0)) >0 else 'Not yet',
                    'queued': True if watch.get('uuid') in queue_list else False,
                    'paused': True if watch.get('paused') else False,
                    'notification_muted': True if watch.get('notification_muted') else False,
                    'unviewed': watch.has_unviewed,
                    'uuid': watch.get('uuid'),
                }
                self.socketio.emit("watch_update", watch_data)
                logger.debug(f"Socket.IO: Emitted update for watch {watch.get('uuid')}")

        except Exception as e:
            logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


    def run(self, host='0.0.0.0', port=5005):
        """Run the Socket.IO server on a separate port"""
        # Start the background task when the server starts
        #self.start_background_task()
        
        # Run the Socket.IO server
        # Use 0.0.0.0 to listen on all interfaces
        logger.info(f"Starting Socket.IO server on http://{host}:{port}")
        self.socketio.run(self.main_app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)