#!/usr/bin/env python3

# Read more https://github.com/dgtlmoon/changedetection.io/wiki

__version__ = '0.50.4'

from changedetectionio.strtobool import strtobool
from json.decoder import JSONDecodeError
import os
import getopt
import platform
import signal

import sys

# Eventlet completely removed - using threading mode for SocketIO
# This provides better Python 3.12+ compatibility and eliminates eventlet/asyncio conflicts
from changedetectionio import store
from changedetectionio.flask_app import changedetection_app
from loguru import logger

# Only global so we can access it in the signal handler
app = None
datastore = None

def get_version():
    return __version__

# Parent wrapper or OS sends us a SIGTERM/SIGINT, do everything required for a clean shutdown
def sigshutdown_handler(_signo, _stack_frame):
    name = signal.Signals(_signo).name
    logger.critical(f'Shutdown: Got Signal - {name} ({_signo}), Fast shutdown initiated')
    
    # Set exit flag immediately to stop all loops
    app.config.exit.set()
    datastore.stop_thread = True
    
    # Shutdown workers immediately
    try:
        from changedetectionio import worker_handler
        worker_handler.shutdown_workers()
    except Exception as e:
        logger.error(f"Error shutting down workers: {str(e)}")
    
    # Shutdown socketio server fast
    from changedetectionio.flask_app import socketio_server
    if socketio_server and hasattr(socketio_server, 'shutdown'):
        try:
            socketio_server.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down Socket.IO server: {str(e)}")
    
    # Save data quickly
    try:
        datastore.sync_to_json()
        logger.success('Fast sync to disk complete.')
    except Exception as e:
        logger.error(f"Error syncing to disk: {str(e)}")
    
    sys.exit()

def main():
    global datastore
    global app

    datastore_path = None
    do_cleanup = False
    host = os.environ.get("LISTEN_HOST", "0.0.0.0").strip()
    port = int(os.environ.get('PORT', 5000))
    ssl_mode = False

    # On Windows, create and use a default path.
    if os.name == 'nt':
        datastore_path = os.path.expandvars(r'%APPDATA%\changedetection.io')
        os.makedirs(datastore_path, exist_ok=True)
    else:
        # Must be absolute so that send_from_directory doesnt try to make it relative to backend/
        datastore_path = os.path.join(os.getcwd(), "../datastore")

    try:
        opts, args = getopt.getopt(sys.argv[1:], "6Ccsd:h:p:l:", "port")
    except getopt.GetoptError:
        print('backend.py -s SSL enable -h [host] -p [port] -d [datastore path] -l [debug level - TRACE, DEBUG(default), INFO, SUCCESS, WARNING, ERROR, CRITICAL]')
        sys.exit(2)

    create_datastore_dir = False

    # Set a default logger level
    logger_level = 'DEBUG'
    # Set a logger level via shell env variable
    # Used: Dockerfile for CICD
    # To set logger level for pytest, see the app function in tests/conftest.py
    if os.getenv("LOGGER_LEVEL"):
        level = os.getenv("LOGGER_LEVEL")
        logger_level = int(level) if level.isdigit() else level.upper()

    for opt, arg in opts:
        if opt == '-s':
            ssl_mode = True

        if opt == '-h':
            host = arg

        if opt == '-p':
            port = int(arg)

        if opt == '-d':
            datastore_path = arg

        # Cleanup (remove text files that arent in the index)
        if opt == '-c':
            do_cleanup = True

        # Create the datadir if it doesnt exist
        if opt == '-C':
            create_datastore_dir = True

        if opt == '-l':
            logger_level = int(arg) if arg.isdigit() else arg.upper()


    logger.success(f"changedetection.io version {get_version()} starting.")
    # Launch using SocketIO run method for proper integration (if enabled)
    ssl_cert_file = os.getenv("SSL_CERT_FILE", 'cert.pem')
    ssl_privkey_file = os.getenv("SSL_PRIVKEY_FILE", 'privkey.pem')
    if os.getenv("SSL_CERT_FILE") and os.getenv("SSL_PRIVKEY_FILE"):
        ssl_mode = True

    # SSL mode could have been set by -s too, therefor fallback to default values
    if ssl_mode:
        if not os.path.isfile(ssl_cert_file) or not os.path.isfile(ssl_privkey_file):
            logger.critical(f"Cannot start SSL/HTTPS mode, Please be sure that {ssl_cert_file}' and '{ssl_privkey_file}' exist in in {os.getcwd()}")
            os._exit(2)

    # Without this, a logger will be duplicated
    logger.remove()
    try:
        log_level_for_stdout = { 'TRACE', 'DEBUG', 'INFO', 'SUCCESS' }
        logger.configure(handlers=[
            {"sink": sys.stdout, "level": logger_level,
             "filter" : lambda record: record['level'].name in log_level_for_stdout},
            {"sink": sys.stderr, "level": logger_level,
             "filter": lambda record: record['level'].name not in log_level_for_stdout},
            ])
    # Catch negative number or wrong log level name
    except ValueError:
        print("Available log level names: TRACE, DEBUG(default), INFO, SUCCESS,"
              " WARNING, ERROR, CRITICAL")
        sys.exit(2)

    # isnt there some @thingy to attach to each route to tell it, that this route needs a datastore
    app_config = {'datastore_path': datastore_path}

    if not os.path.isdir(app_config['datastore_path']):
        if create_datastore_dir:
            os.mkdir(app_config['datastore_path'])
        else:
            logger.critical(
                f"ERROR: Directory path for the datastore '{app_config['datastore_path']}'"
                f" does not exist, cannot start, please make sure the"
                f" directory exists or specify a directory with the -d option.\n"
                f"Or use the -C parameter to create the directory.")
            sys.exit(2)

    try:
        datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], version_tag=__version__)
    except JSONDecodeError as e:
        # Dont' start if the JSON DB looks corrupt
        logger.critical(f"ERROR: JSON DB or Proxy List JSON at '{app_config['datastore_path']}' appears to be corrupt, aborting.")
        logger.critical(str(e))
        return

    app = changedetection_app(app_config, datastore)

    # Get the SocketIO instance from the Flask app (created in flask_app.py)
    from changedetectionio.flask_app import socketio_server
    global socketio
    socketio = socketio_server

    signal.signal(signal.SIGTERM, sigshutdown_handler)
    signal.signal(signal.SIGINT, sigshutdown_handler)
    
    # Custom signal handler for memory cleanup
    def sigusr_clean_handler(_signo, _stack_frame):
        from changedetectionio.gc_cleanup import memory_cleanup
        logger.info('SIGUSR1 received: Running memory cleanup')
        return memory_cleanup(app)

    # Register the SIGUSR1 signal handler
    # Only register the signal handler if running on Linux
    if platform.system() == "Linux":
        signal.signal(signal.SIGUSR1, sigusr_clean_handler)
    else:
        logger.info("SIGUSR1 handler only registered on Linux, skipped.")

    # Go into cleanup mode
    if do_cleanup:
        datastore.remove_unused_snapshots()

    app.config['datastore_path'] = datastore_path


    @app.context_processor
    def inject_template_globals():
        return dict(right_sticky="v{}".format(datastore.data['version_tag']),
                    new_version_available=app.config['NEW_VERSION_AVAILABLE'],
                    has_password=datastore.data['settings']['application']['password'] != False,
                    socket_io_enabled=datastore.data['settings']['application']['ui'].get('socket_io_enabled', True)
                    )

    # Monitored websites will not receive a Referer header when a user clicks on an outgoing link.
    @app.after_request
    def hide_referrer(response):
        if strtobool(os.getenv("HIDE_REFERER", 'false')):
            response.headers["Referrer-Policy"] = "same-origin"

        return response

    # Proxy sub-directory support
    # Set environment var USE_X_SETTINGS=1 on this script
    # And then in your proxy_pass settings
    #
    #         proxy_set_header Host "localhost";
    #         proxy_set_header X-Forwarded-Prefix /app;


    if os.getenv('USE_X_SETTINGS'):
        logger.info("USE_X_SETTINGS is ENABLED")
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1, x_host=1)


    # SocketIO instance is already initialized in flask_app.py
    if socketio_server:
        if ssl_mode:
            logger.success(f"SSL mode enabled, attempting to start with '{ssl_cert_file}' and '{ssl_privkey_file}' in {os.getcwd()}")
            socketio.run(app, host=host, port=int(port), debug=False,
                         ssl_context=(ssl_cert_file, ssl_privkey_file), allow_unsafe_werkzeug=True)
        else:
            socketio.run(app, host=host, port=int(port), debug=False, allow_unsafe_werkzeug=True)
    else:
        # Run Flask app without Socket.IO if disabled
        logger.info("Starting Flask app without Socket.IO server")
        if ssl_mode:
            logger.success(f"SSL mode enabled, attempting to start with '{ssl_cert_file}' and '{ssl_privkey_file}' in {os.getcwd()}")
            app.run(host=host, port=int(port), debug=False,
                    ssl_context=(ssl_cert_file, ssl_privkey_file))
        else:
            app.run(host=host, port=int(port), debug=False)
