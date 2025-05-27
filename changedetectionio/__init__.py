#!/usr/bin/env python3

# Read more https://github.com/dgtlmoon/changedetection.io/wiki

__version__ = '0.49.18'

from changedetectionio.strtobool import strtobool
from json.decoder import JSONDecodeError
import os
import getopt
import platform
import signal
import socket
import sys
from werkzeug.serving import run_simple

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
    logger.critical(f'Shutdown: Got Signal - {name} ({_signo}), Saving DB to disk and calling shutdown')
    datastore.sync_to_json()
    logger.success('Sync JSON to disk complete.')
    
    # Shutdown socketio server if available
    from changedetectionio.flask_app import socketio_server
    if socketio_server and hasattr(socketio_server, 'shutdown'):
        try:
            logger.info("Shutting down Socket.IO server...")
            socketio_server.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down Socket.IO server: {str(e)}")
    
    # Set flags for clean shutdown
    datastore.stop_thread = True
    app.config.exit.set()
    sys.exit()

def main():
    global datastore
    global app

    datastore_path = None
    do_cleanup = False
    host = ''
    ipv6_enabled = False
    port = os.environ.get('PORT') or 5000
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

        if opt == '-6':
            logger.success("Enabling IPv6 listen support")
            ipv6_enabled = True

        # Cleanup (remove text files that arent in the index)
        if opt == '-c':
            do_cleanup = True

        # Create the datadir if it doesnt exist
        if opt == '-C':
            create_datastore_dir = True

        if opt == '-l':
            logger_level = int(arg) if arg.isdigit() else arg.upper()

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
    def inject_version():
        return dict(right_sticky="v{}".format(datastore.data['version_tag']),
                    new_version_available=app.config['NEW_VERSION_AVAILABLE'],
                    has_password=datastore.data['settings']['application']['password'] != False
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

    s_type = socket.AF_INET6 if ipv6_enabled else socket.AF_INET

    # Get socketio_server from flask_app
    from changedetectionio.flask_app import socketio_server

    if socketio_server and datastore.data['settings']['application']['ui'].get('open_diff_in_new_tab'):
        logger.info("Starting server with Socket.IO support (using threading)...")

        # Use Flask-SocketIO's run method with error handling for Werkzeug warning
        # This is the cleanest approach that works with all Flask-SocketIO versions
        # Use '0.0.0.0' as the default host if none is specified
        # This will listen on all available interfaces
        listen_host = '0.0.0.0' if host == '' else host
        logger.info(f"Using host: {listen_host} and port: {port}")

        try:
            # First try with the allow_unsafe_werkzeug parameter (newer versions)
            if ssl_mode:
                socketio_server.run(
                    app,
                    host=listen_host,
                    port=int(port),
                    certfile='cert.pem',
                    keyfile='privkey.pem',
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True  # Only in newer versions
                )
            else:
                socketio_server.run(
                    app,
                    host=listen_host,
                    port=int(port),
                    debug=False,
                    use_reloader=False,
                    allow_unsafe_werkzeug=True  # Only in newer versions
                )
        except TypeError:
            # If allow_unsafe_werkzeug is not a valid parameter, try without it
            logger.info("Falling back to basic run method without allow_unsafe_werkzeug")
            # Override the werkzeug safety check by setting an environment variable
            os.environ['WERKZEUG_RUN_MAIN'] = 'true'
            if ssl_mode:
                socketio_server.run(
                    app,
                    host=listen_host,
                    port=int(port),
                    certfile='cert.pem',
                    keyfile='privkey.pem',
                    debug=False,
                    use_reloader=False
                )
            else:
                socketio_server.run(
                    app,
                    host=listen_host,
                    port=int(port),
                    debug=False,
                    use_reloader=False
                )
    else:
        logger.warning("Socket.IO server not initialized, falling back to standard WSGI server")
        # Fallback to standard WSGI server if socketio_server is not available
        listen_host = '0.0.0.0' if host == '' else host
        if ssl_mode:
            # Use Werkzeug's run_simple with SSL support
            run_simple(
                hostname=listen_host,
                port=int(port),
                application=app,
                use_reloader=False,
                use_debugger=False,
                ssl_context=('cert.pem', 'privkey.pem')
            )
        else:
            # Use Werkzeug's run_simple for standard HTTP
            run_simple(
                hostname=listen_host,
                port=int(port),
                application=app,
                use_reloader=False,
                use_debugger=False
            )

