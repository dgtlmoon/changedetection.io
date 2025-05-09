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
    def __init__(self, socketio_instance, datastore):
        self.socketio_instance = socketio_instance
        self.datastore = datastore

        # Connect to the watch_check_completed signal
        from changedetectionio.flask_app import watch_check_completed as wcc
        wcc.connect(self.handle_signal, weak=False)
        logger.info("SignalHandler: Connected to signal from direct import")

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


def handle_watch_update(socketio, **kwargs):
    """Handle watch update signal from blinker"""
    try:
        watch = kwargs.get('watch')
        datastore = kwargs.get('datastore')

        # Emit the watch update to all connected clients
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
        socketio.emit("watch_update", watch_data)
        logger.debug(f"Socket.IO: Emitted update for watch {watch.get('uuid')}")

    except Exception as e:
        logger.error(f"Socket.IO error in handle_watch_update: {str(e)}")


def init_socketio(app, datastore):
    """Initialize SocketIO with the main Flask app"""
    # Use threading mode only - eventlet monkey patching causes issues
    # when patching after other modules have been imported
    async_mode = 'threading'
    logger.info("Using threading mode for Socket.IO (long-polling transport)")

    socketio = SocketIO(app,
                      async_mode=async_mode,  # Use eventlet if available, otherwise threading
                      cors_allowed_origins="*",
                      logger=True,
                      engineio_logger=True)

    # Set up event handlers
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        logger.info("Socket.IO: Client connected")

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        logger.info("Socket.IO: Client disconnected")

    # Create a dedicated signal handler that will receive signals and emit them to clients
    signal_handler = SignalHandler(socketio, datastore)

    # Store the datastore reference on the socketio object for later use
    socketio.datastore = datastore

    logger.info("Socket.IO initialized and attached to main Flask app")
    return socketio
