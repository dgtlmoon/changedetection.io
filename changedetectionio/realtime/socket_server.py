from flask import Flask
from flask_socketio import SocketIO
import threading
import json
import time
from loguru import logger

class ChangeDetectionSocketIO:
    def __init__(self, app, datastore):
        self.main_app = app
        self.datastore = datastore
        
        # Create a separate app for Socket.IO
        self.app = Flask(__name__)
        
        # Use threading mode instead of eventlet
        self.socketio = SocketIO(self.app, 
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
        
        # Set up a simple index route for the Socket.IO app
        @self.app.route('/')
        def index():
            return """
            <html>
                <head>
                    <title>ChangeDetection.io Socket.IO Server</title>
                </head>
                <body>
                    <h1>ChangeDetection.io Socket.IO Server</h1>
                    <p>This is the Socket.IO server for ChangeDetection.io real-time updates.</p>
                    <p>Socket.IO endpoint is available at: <code>/socket.io/</code></p>
                </body>
            </html>
            """
        
    def start_background_task(self):
        """Start the background task if it's not already running"""
        with self.thread_lock:
            if self.thread is None:
                self.thread = threading.Thread(target=self.background_task)
                self.thread.daemon = True
                self.thread.start()
                logger.info("Socket.IO: Started background task thread")
    
    def handle_connect(self):
        """Handle client connection"""
        logger.info("Socket.IO: Client connected")
        
        # Start the background task when the first client connects
        self.start_background_task()
    
    def handle_disconnect(self):
        """Handle client disconnection"""
        logger.info("Socket.IO: Client disconnected")
    
    def background_task(self):
        """Background task that emits watch status periodically"""
        check_interval = 4  # seconds between updates
        
        try:
            with self.main_app.app_context():
                while True:
                    try:
                        # Collect all watch data
                        watches_data = []
                        
                        # Get list of watches that are currently running
                        from changedetectionio.flask_app import running_update_threads
                        currently_checking = []
                        
                        # Make a copy to avoid issues if the list changes
                        threads_snapshot = list(running_update_threads)
                        for thread in threads_snapshot:
                            if hasattr(thread, 'current_uuid') and thread.current_uuid:
                                currently_checking.append(thread.current_uuid)
                        
                        # Send all watch data periodically
                        for uuid, watch in self.datastore.data['watching'].items():
                            # Simplified watch data to avoid sending everything
                            simplified_data = {
                                'uuid': uuid,
                                'url': watch.get('url', ''),
                                'title': watch.get('title', ''),
                                'last_checked': int(watch.get('last_checked', 0)),
                                'last_changed': int(watch.get('newest_history_key', 0)),
                                'history_n': watch.history_n if hasattr(watch, 'history_n') else 0,
                                'unviewed_history': int(watch.get('newest_history_key', 0)) > int(watch.get('last_viewed', 0)) and watch.history_n >=2,
                                'paused': watch.get('paused', False),
                                'checking': uuid in currently_checking
                            }
                            watches_data.append(simplified_data)
                        
                        # Emit all watch data periodically
                        self.socketio.emit('watch_data', watches_data)
                        logger.debug(f"Socket.IO: Emitted watch data for {len(watches_data)} watches")
                        
                    except Exception as e:
                        logger.error(f"Socket.IO error in background task: {str(e)}")
                    
                    # Wait before next update
                    time.sleep(check_interval)
            
        except Exception as e:
            logger.error(f"Socket.IO background task failed: {str(e)}")
            
    def run(self, host='0.0.0.0', port=5005):
        """Run the Socket.IO server on a separate port"""
        # Start the background task when the server starts
        self.start_background_task()
        
        # Run the Socket.IO server
        # Use 0.0.0.0 to listen on all interfaces
        logger.info(f"Starting Socket.IO server on http://{host}:{port}")
        self.socketio.run(self.app, host=host, port=port, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)