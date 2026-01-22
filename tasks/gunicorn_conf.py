# Gunicorn configuration for TicketWatch on Fly.io
# Used with: gunicorn -c tasks/gunicorn_conf.py changedetection:app

import os
import multiprocessing

# Bind to all interfaces on the specified port
bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"

# Worker configuration
# Use threading worker for Flask-SocketIO compatibility
worker_class = "gthread"
workers = 1  # Single worker for Socket.IO state sharing
threads = 4  # Multiple threads per worker

# Timeout settings - generous for Playwright browser operations
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
accesslog = "-"  # stdout
errorlog = "-"   # stderr
capture_output = True

# Process naming
proc_name = "ticketwatch"

# Prevent worker recycling issues
max_requests = 0  # Disable - we manage memory ourselves
max_requests_jitter = 0

# Preload app for faster startup (but not with Socket.IO - needs separate workers)
preload_app = False

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# SSL - handled by Fly.io proxy
forwarded_allow_ips = "*"
proxy_allow_from = "*"

# Hook to handle Socket.IO with threading mode
def post_fork(server, worker):
    """Called after a worker has been forked."""
    pass

def on_starting(server):
    """Called before the master process is initialized."""
    pass
