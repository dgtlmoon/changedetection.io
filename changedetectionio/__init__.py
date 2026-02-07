#!/usr/bin/env python3

# Read more https://github.com/dgtlmoon/changedetection.io/wiki
# Semver means never use .01, or 00. Should be .1.
__version__ = '0.52.9'

from changedetectionio.strtobool import strtobool
from json.decoder import JSONDecodeError

from loguru import logger
import getopt
import logging
import os
import platform
import signal
import threading
import time

# Eventlet completely removed - using threading mode for SocketIO
# This provides better Python 3.12+ compatibility and eliminates eventlet/asyncio conflicts
# Note: store and changedetection_app are imported inside main() to avoid
# initialization before argument parsing (allows --help to work without loading everything)

# ==============================================================================
# Multiprocessing Configuration - CRITICAL for Thread Safety
# ==============================================================================
#
# PROBLEM: Python 3.12+ warns about fork() with multi-threaded processes:
#   "This process is multi-threaded, use of fork() may lead to deadlocks"
#
# WHY IT'S DANGEROUS:
#   1. This Flask app has multiple threads (HTTP handlers, workers, SocketIO)
#   2. fork() copies ONLY the calling thread to the child process
#   3. BUT fork() also copies all locks/mutexes in their current state
#   4. If another thread held a lock during fork() → child has locked lock with no owner
#   5. Result: PERMANENT DEADLOCK if child tries to acquire that lock
#
# SOLUTION: Use 'spawn' instead of 'fork'
#   - spawn starts a fresh Python interpreter (no inherited threads or locks)
#   - Slower (~200ms vs ~1ms) but safe with multi-threaded parent
#   - Consistent across all platforms (Windows already uses spawn by default)
#
# IMPLEMENTATION:
#   1. Explicit contexts everywhere (primary protection):
#      - playwright.py: ctx = multiprocessing.get_context('spawn')
#      - puppeteer.py: ctx = multiprocessing.get_context('spawn')
#      - isolated_opencv.py: ctx = multiprocessing.get_context('spawn')
#      - isolated_libvips.py: ctx = multiprocessing.get_context('spawn')
#
#   2. Global default (defense-in-depth, below):
#      - Safety net if future code forgets explicit context
#      - Protects against third-party libraries using Process()
#      - Costs nothing (explicit contexts always override it)
#
# WHY BOTH?
#   - Explicit contexts: Clear, self-documenting, always works
#   - Global default: Safety net for forgotten contexts or library code
#   - If someone writes "Process()" instead of "ctx.Process()", still safe!
#
# See: https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
# ==============================================================================

import multiprocessing
import sys

# Set spawn as global default (safety net - all our code uses explicit contexts anyway)
# Skip in tests to avoid breaking pytest-flask's LiveServer fixture (uses unpicklable local functions)
if 'pytest' not in sys.modules:
    try:
        if multiprocessing.get_start_method(allow_none=True) is None:
            multiprocessing.set_start_method('spawn', force=False)
            logger.debug("Set multiprocessing default to 'spawn' for thread safety (explicit contexts used everywhere)")
    except RuntimeError:
        logger.debug(f"Multiprocessing start method already set: {multiprocessing.get_start_method()}")

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

    # Log memory consumption before shutting down workers (cross-platform)
    try:
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        rss_mb = mem_info.rss / 1024 / 1024
        vms_mb = mem_info.vms / 1024 / 1024
        logger.info(f"Memory consumption before worker shutdown: RSS={rss_mb:,.2f} MB, VMS={vms_mb:,.2f} MB")
    except Exception as e:
        logger.warning(f"Could not retrieve memory stats: {str(e)}")

    # Shutdown workers and queues immediately
    try:
        from changedetectionio import worker_pool
        worker_pool.shutdown_workers()
    except Exception as e:
        logger.error(f"Error shutting down workers: {str(e)}")
    
    # Close janus queues properly
    try:
        from changedetectionio.flask_app import update_q, notification_q
        update_q.close()
        notification_q.close()
        logger.debug("Queues closed successfully")
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to close queues: {e}")
    
    # Shutdown socketio server fast
    from changedetectionio.flask_app import socketio_server
    if socketio_server and hasattr(socketio_server, 'shutdown'):
        try:
            socketio_server.shutdown()
        except Exception as e:
            logger.error(f"Error shutting down Socket.IO server: {str(e)}")
    
    # With immediate persistence, all data is already saved
    logger.success('All data already persisted (immediate commits enabled).')

    sys.exit()

def print_help():
    """Print help text for command line options"""
    print('Usage: changedetection.py [options]')
    print('')
    print('Standard options:')
    print('  -s                SSL enable')
    print('  -h HOST           Listen host (default: 0.0.0.0)')
    print('  -p PORT           Listen port (default: 5000)')
    print('  -d PATH           Datastore path')
    print('  -l LEVEL          Log level (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL)')
    print('  -c                Cleanup unused snapshots')
    print('  -C                Create datastore directory if it doesn\'t exist')
    print('  -P true/false     Set all watches paused (true) or active (false)')
    print('')
    print('Add URLs on startup:')
    print('  -u URL            Add URL to watch (can be used multiple times)')
    print('  -u0 \'JSON\'        Set options for first -u URL (e.g. \'{"processor":"text_json_diff"}\')')
    print('  -u1 \'JSON\'        Set options for second -u URL (0-indexed)')
    print('  -u2 \'JSON\'        Set options for third -u URL, etc.')
    print('                    Available options: processor, fetch_backend, headers, method, etc.')
    print('                    See model/Watch.py for all available options')
    print('')
    print('Recheck on startup:')
    print('  -r all            Queue all watches for recheck on startup')
    print('  -r UUID,...       Queue specific watches (comma-separated UUIDs)')
    print('  -r all N          Queue all watches, wait for completion, repeat N times')
    print('  -r UUID,... N     Queue specific watches, wait for completion, repeat N times')
    print('')
    print('Batch mode:')
    print('  -b                Run in batch mode (process queue then exit)')
    print('                    Useful for CI/CD, cron jobs, or one-time checks')
    print('                    NOTE: Batch mode checks if Flask is running and aborts if port is in use')
    print('                    Use -p PORT to specify a different port if needed')
    print('')

def main():
    global datastore
    global app

    # Early help/version check before any initialization
    if '--help' in sys.argv or '-help' in sys.argv:
        print_help()
        sys.exit(0)

    if '--version' in sys.argv or '-v' in sys.argv:
        print(f'changedetection.io {__version__}')
        sys.exit(0)

    # Import heavy modules after help/version checks to keep startup fast for those flags
    from changedetectionio import store
    from changedetectionio.flask_app import changedetection_app

    datastore_path = None
    # Set a default logger level
    logger_level = 'DEBUG'
    include_default_watches = True
    all_paused = None  # None means don't change, True/False to set

    host = os.environ.get("LISTEN_HOST", "0.0.0.0").strip()
    port = int(os.environ.get('PORT', 5000))
    ssl_mode = False

    # Lists for multiple URLs and their options
    urls_to_add = []
    url_options = {}  # Key: index (0-based), Value: dict of options
    recheck_watches = None  # None, 'all', or list of UUIDs
    recheck_repeat_count = 1  # Number of times to repeat recheck cycle
    batch_mode = False  # Run once then exit when queue is empty

    # On Windows, create and use a default path.
    if os.name == 'nt':
        datastore_path = os.path.expandvars(r'%APPDATA%\changedetection.io')
        os.makedirs(datastore_path, exist_ok=True)
    else:
        # Must be absolute so that send_from_directory doesnt try to make it relative to backend/
        datastore_path = os.path.join(os.getcwd(), "../datastore")

    # Pre-process arguments to extract -u, -u<N>, and -r options before getopt
    # This allows unlimited -u0, -u1, -u2, ... options without predefining them
    cleaned_argv = ['changedetection.py']  # Start with program name
    i = 1
    while i < len(sys.argv):
        arg = sys.argv[i]

        # Handle -u (add URL)
        if arg == '-u' and i + 1 < len(sys.argv):
            urls_to_add.append(sys.argv[i + 1])
            i += 2
            continue

        # Handle -u<N> (set options for URL at index N)
        if arg.startswith('-u') and len(arg) > 2 and arg[2:].isdigit():
            idx = int(arg[2:])
            if i + 1 < len(sys.argv):
                try:
                    import json
                    url_options[idx] = json.loads(sys.argv[i + 1])
                except json.JSONDecodeError as e:
                    print(f'Error: Invalid JSON for {arg}: {sys.argv[i + 1]}')
                    print(f'JSON decode error: {e}')
                    sys.exit(2)
                i += 2
                continue

        # Handle -r (recheck watches)
        if arg == '-r' and i + 1 < len(sys.argv):
            recheck_arg = sys.argv[i + 1]
            if recheck_arg.lower() == 'all':
                recheck_watches = 'all'
            else:
                # Parse comma-separated list of UUIDs
                recheck_watches = [uuid.strip() for uuid in recheck_arg.split(',') if uuid.strip()]

            # Check for optional repeat count as third argument
            if i + 2 < len(sys.argv) and sys.argv[i + 2].isdigit():
                recheck_repeat_count = int(sys.argv[i + 2])
                if recheck_repeat_count < 1:
                    print(f'Error: Repeat count must be at least 1, got {recheck_repeat_count}')
                    sys.exit(2)
                i += 3
            else:
                i += 2
            continue

        # Handle -b (batch mode - run once and exit)
        if arg == '-b':
            batch_mode = True
            i += 1
            continue

        # Keep other arguments for getopt
        cleaned_argv.append(arg)
        i += 1

    try:
        opts, args = getopt.getopt(cleaned_argv[1:], "6Csd:h:p:l:P:", "port")
    except getopt.GetoptError as e:
        print_help()
        print(f'Error: {e}')
        sys.exit(2)

    create_datastore_dir = False

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

        # Create the datadir if it doesnt exist
        if opt == '-C':
            create_datastore_dir = True

        if opt == '-l':
            logger_level = int(arg) if arg.isdigit() else arg.upper()

        if opt == '-P':
            try:
                all_paused = bool(strtobool(arg))
            except ValueError:
                print(f'Error: Invalid value for -P option: {arg}')
                print('Expected: true, false, yes, no, 1, or 0')
                sys.exit(2)

    # If URLs are provided, don't include default watches
    if urls_to_add:
        include_default_watches = False


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

    # Disable verbose pyppeteer logging to prevent memory leaks from large CDP messages
    # Set both parent and child loggers since pyppeteer hardcodes DEBUG level
    logging.getLogger('pyppeteer.connection').setLevel(logging.WARNING)
    logging.getLogger('pyppeteer.connection.Connection').setLevel(logging.WARNING)

    # isnt there some @thingy to attach to each route to tell it, that this route needs a datastore
    app_config = {
        'datastore_path': datastore_path,
        'batch_mode': batch_mode,
        'recheck_watches': recheck_watches,
        'recheck_repeat_count': recheck_repeat_count
    }

    if not os.path.isdir(app_config['datastore_path']):
        if create_datastore_dir:
            os.makedirs(app_config['datastore_path'], exist_ok=True)
        else:
            logger.critical(
                f"ERROR: Directory path for the datastore '{app_config['datastore_path']}'"
                f" does not exist, cannot start, please make sure the"
                f" directory exists or specify a directory with the -d option.\n"
                f"Or use the -C parameter to create the directory.")
            sys.exit(2)

    try:
        datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], version_tag=__version__, include_default_watches=include_default_watches)
    except JSONDecodeError as e:
        # Dont' start if the JSON DB looks corrupt
        logger.critical(f"ERROR: JSON DB or Proxy List JSON at '{app_config['datastore_path']}' appears to be corrupt, aborting.")
        logger.critical(str(e))
        return

    # Apply all_paused setting if specified via CLI
    if all_paused is not None:
        datastore.data['settings']['application']['all_paused'] = all_paused
        logger.info(f"Setting all watches paused: {all_paused}")

    # Inject datastore into plugins that need access to settings
    from changedetectionio.pluggy_interface import inject_datastore_into_plugins
    inject_datastore_into_plugins(datastore)

    # Step 1: Add URLs with their options (if provided via -u flags)
    added_watch_uuids = []
    if urls_to_add:
        logger.info(f"Adding {len(urls_to_add)} URL(s) from command line")
        for idx, url in enumerate(urls_to_add):
            extras = url_options.get(idx, {})
            if extras:
                logger.debug(f"Adding watch {idx}: {url} with options: {extras}")
            else:
                logger.debug(f"Adding watch {idx}: {url}")

            new_uuid = datastore.add_watch(url=url, extras=extras)
            if new_uuid:
                added_watch_uuids.append(new_uuid)
                logger.success(f"Added watch: {url} (UUID: {new_uuid})")
            else:
                logger.error(f"Failed to add watch: {url}")

    app = changedetection_app(app_config, datastore)

    # Step 2: Queue newly added watches (if -u was provided in batch mode)
    # This must happen AFTER app initialization so update_q is available
    if batch_mode and added_watch_uuids:
        from changedetectionio.flask_app import update_q
        from changedetectionio import queuedWatchMetaData, worker_pool

        logger.info(f"Batch mode: Queuing {len(added_watch_uuids)} newly added watches")
        for watch_uuid in added_watch_uuids:
            try:
                worker_pool.queue_item_async_safe(
                    update_q,
                    queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid})
                )
                logger.debug(f"Queued newly added watch: {watch_uuid}")
            except Exception as e:
                logger.error(f"Failed to queue watch {watch_uuid}: {e}")

    # Step 3: Queue watches for recheck (if -r was provided)
    # This must happen AFTER app initialization so update_q is available
    if recheck_watches is not None:
        from changedetectionio.flask_app import update_q
        from changedetectionio import queuedWatchMetaData, worker_pool

        watches_to_queue = []
        if recheck_watches == 'all':
            # Queue all watches, excluding those already queued in batch mode
            all_watches = list(datastore.data['watching'].keys())
            if batch_mode and added_watch_uuids:
                # Exclude newly added watches that were already queued in batch mode
                watches_to_queue = [uuid for uuid in all_watches if uuid not in added_watch_uuids]
                logger.info(f"Queuing {len(watches_to_queue)} existing watches for recheck ({len(added_watch_uuids)} newly added watches already queued)")
            else:
                watches_to_queue = all_watches
                logger.info(f"Queuing all {len(watches_to_queue)} watches for recheck")
        else:
            # Queue specific UUIDs
            watches_to_queue = recheck_watches
            logger.info(f"Queuing {len(watches_to_queue)} specific watches for recheck")

        queued_count = 0
        for watch_uuid in watches_to_queue:
            if watch_uuid in datastore.data['watching']:
                try:
                    worker_pool.queue_item_async_safe(
                        update_q,
                        queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid})
                    )
                    queued_count += 1
                    logger.debug(f"Queued watch for recheck: {watch_uuid}")
                except Exception as e:
                    logger.error(f"Failed to queue watch {watch_uuid}: {e}")
            else:
                logger.warning(f"Watch UUID not found in datastore: {watch_uuid}")

        logger.success(f"Successfully queued {queued_count} watches for recheck")

    # Step 4: Setup batch mode monitor (if -b was provided)
    if batch_mode:
        from changedetectionio.flask_app import update_q

        # Safety check: Ensure Flask app is not already running on this port
        # Batch mode should never run alongside the web server
        import socket
        test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        try:
            # Try to bind to the configured host:port (no SO_REUSEADDR - strict check)
            test_socket.bind((host, port))
            test_socket.close()
            logger.debug(f"Batch mode: Port {port} is available (Flask app not running)")
        except OSError as e:
            test_socket.close()
            # errno 98 = EADDRINUSE (Linux)
            # errno 48 = EADDRINUSE (macOS)
            # errno 10048 = WSAEADDRINUSE (Windows)
            if e.errno in (48, 98, 10048) or "Address already in use" in str(e) or "already in use" in str(e).lower():
                logger.critical(f"ERROR: Batch mode cannot run - port {port} is already in use")
                logger.critical(f"The Flask web server appears to be running on {host}:{port}")
                logger.critical(f"Batch mode is designed for standalone operation (CI/CD, cron jobs, etc.)")
                logger.critical(f"Please either stop the Flask web server, or use a different port with -p PORT")
                sys.exit(1)
            else:
                # Some other socket error - log but continue (might be network configuration issue)
                logger.warning(f"Port availability check failed with unexpected error: {e}")
                logger.warning(f"Continuing with batch mode anyway - be aware of potential conflicts")

        def queue_watches_for_recheck(datastore, iteration):
            """Helper function to queue watches for recheck"""
            watches_to_queue = []
            if recheck_watches == 'all':
                all_watches = list(datastore.data['watching'].keys())
                if batch_mode and added_watch_uuids and iteration == 1:
                    # Only exclude newly added watches on first iteration
                    watches_to_queue = [uuid for uuid in all_watches if uuid not in added_watch_uuids]
                else:
                    watches_to_queue = all_watches
                logger.info(f"Batch mode (iteration {iteration}): Queuing all {len(watches_to_queue)} watches")
            elif recheck_watches:
                watches_to_queue = recheck_watches
                logger.info(f"Batch mode (iteration {iteration}): Queuing {len(watches_to_queue)} specific watches")

            queued_count = 0
            for watch_uuid in watches_to_queue:
                if watch_uuid in datastore.data['watching']:
                    try:
                        worker_pool.queue_item_async_safe(
                            update_q,
                            queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid})
                        )
                        queued_count += 1
                    except Exception as e:
                        logger.error(f"Failed to queue watch {watch_uuid}: {e}")
                else:
                    logger.warning(f"Watch UUID not found in datastore: {watch_uuid}")
            logger.success(f"Batch mode (iteration {iteration}): Successfully queued {queued_count} watches")
            return queued_count

        def batch_mode_monitor():
            """Monitor queue and workers, shutdown or repeat when work is complete"""
            import time

            # Track iterations if repeat mode is enabled
            current_iteration = 1
            total_iterations = recheck_repeat_count if recheck_watches and recheck_repeat_count > 1 else 1

            if total_iterations > 1:
                logger.info(f"Batch mode: Will repeat recheck {total_iterations} times")
            else:
                logger.info("Batch mode: Waiting for all queued items to complete...")

            # Wait a bit for workers to start processing
            time.sleep(3)

            try:
                while current_iteration <= total_iterations:
                    logger.info(f"Batch mode: Waiting for iteration {current_iteration}/{total_iterations} to complete...")

                    # Use the shared wait_for_all_checks function
                    completed = worker_pool.wait_for_all_checks(update_q, timeout=300)

                    if not completed:
                        logger.warning(f"Batch mode: Iteration {current_iteration} timed out after 300 seconds")

                    logger.success(f"Batch mode: Iteration {current_iteration}/{total_iterations} completed")

                    # Check if we need to repeat
                    if current_iteration < total_iterations:
                        logger.info(f"Batch mode: Starting iteration {current_iteration + 1}...")
                        current_iteration += 1

                        # Re-queue watches for next iteration
                        queue_watches_for_recheck(datastore, current_iteration)

                        # Brief pause before continuing
                        time.sleep(2)
                    else:
                        # All iterations complete
                        logger.success(f"Batch mode: All {total_iterations} iterations completed, initiating shutdown")
                        # Trigger shutdown
                        import os, signal
                        os.kill(os.getpid(), signal.SIGTERM)
                        return

            except Exception as e:
                logger.error(f"Batch mode monitor error: {e}")
                logger.error(f"Initiating emergency shutdown")
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)

        # Start monitor in background thread
        monitor_thread = threading.Thread(target=batch_mode_monitor, daemon=True, name="BatchModeMonitor")
        monitor_thread.start()
        logger.info("Batch mode enabled: Will exit after all queued items are processed")

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

    app.config['datastore_path'] = datastore_path


    @app.context_processor
    def inject_template_globals():
        return dict(right_sticky="v{}".format(datastore.data['version_tag']),
                    new_version_available=app.config['NEW_VERSION_AVAILABLE'],
                    has_password=datastore.data['settings']['application']['password'] != False,
                    socket_io_enabled=datastore.data['settings']['application'].get('ui', {}).get('socket_io_enabled', True),
                    all_paused=datastore.data['settings']['application'].get('all_paused', False),
                    all_muted=datastore.data['settings']['application'].get('all_muted', False)
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
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=1,      # X-Forwarded-For (client IP)
            x_proto=1,    # X-Forwarded-Proto (http/https)
            x_host=1,     # X-Forwarded-Host (original host)
            x_port=1,     # X-Forwarded-Port (original port)
            x_prefix=1    # X-Forwarded-Prefix (URL prefix)
        )


    # In batch mode, skip starting the HTTP server - just keep workers running
    if batch_mode:
        logger.info("Batch mode: Skipping HTTP server startup, workers will process queue")
        logger.info("Batch mode: Main thread will wait for shutdown signal")
        # Keep main thread alive until batch monitor triggers shutdown
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Batch mode: Keyboard interrupt received")
            pass
    else:
        # Normal mode: Start HTTP server
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
