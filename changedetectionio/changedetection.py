#!/usr/bin/python3

# Launch as a eventlet.wsgi server instance.

from distutils.util import strtobool
from json.decoder import JSONDecodeError

import eventlet
import eventlet.wsgi
import getopt
import os
import signal
import socket
import sys

from . import store, changedetection_app, content_fetcher
from . import __version__

# Only global so we can access it in the signal handler
app = None
datastore = None
is_graceful_shutdown = False

def graceful_shutdown():
    global app
    global datastore
    global is_graceful_shutdown
    # print Gracefully exited message at the end.
    is_graceful_shutdown = True
    print('Gracefully exiting')
    # Stop ChangeDetectionStore thread to avoid conflict with sync_to_json()
    datastore.stop_thread = True
    # Trigger saving data
    datastore.sync_to_json()
    # Stop check_for_new_version, notification_runner, ticker_thread_check_time_launch_checks, update_worker
    app.config.exit.set()
    sys.exit(0)

def sigint_handler(sig, frame):
    #https://docs.python.org/3/library/signal.html#signal.SIG_IGN
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("Catch - CTRL+C")
    graceful_shutdown()

def sigterm_handler(sig, frame):
    print("Catch - SIGTERM")
    graceful_shutdown()

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
        opts, args = getopt.getopt(sys.argv[1:], "6Ccsd:h:p:", "port")
    except getopt.GetoptError:
        print('backend.py -s SSL enable -h [host] -p [port] -d [datastore path]')
        sys.exit(2)

    create_datastore_dir = False

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
            print ("Enabling IPv6 listen support")
            ipv6_enabled = True

        # Cleanup (remove text files that arent in the index)
        if opt == '-c':
            do_cleanup = True

        # Create the datadir if it doesnt exist
        if opt == '-C':
            create_datastore_dir = True

    # isnt there some @thingy to attach to each route to tell it, that this route needs a datastore
    app_config = {'datastore_path': datastore_path}

    if not os.path.isdir(app_config['datastore_path']):
        if create_datastore_dir:
            os.mkdir(app_config['datastore_path'])
        else:
            print(
                "ERROR: Directory path for the datastore '{}' does not exist, cannot start, please make sure the directory exists or specify a directory with the -d option.\n"
                "Or use the -C parameter to create the directory.".format(app_config['datastore_path']), file=sys.stderr)
            sys.exit(2)

    try:
        datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], version_tag=__version__)
    except JSONDecodeError as e:
        # Dont' start if the JSON DB looks corrupt
        print ("ERROR: JSON DB or Proxy List JSON at '{}' appears to be corrupt, aborting".format(app_config['datastore_path']))
        print(str(e))
        return

    app = changedetection_app(app_config, datastore)

    signal.signal(signal.SIGTERM, sigterm_handler)
    signal.signal(signal.SIGINT, sigint_handler)

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
    # @Note: Incompatible with password login (and maybe other features) for now, submit a PR!
    @app.after_request
    def hide_referrer(response):
        if strtobool(os.getenv("HIDE_REFERER", 'false')):
            response.headers["Referrer-Policy"] = "no-referrer"

        return response

    # Proxy sub-directory support
    # Set environment var USE_X_SETTINGS=1 on this script
    # And then in your proxy_pass settings
    #
    #         proxy_set_header Host "localhost";
    #         proxy_set_header X-Forwarded-Prefix /app;

    if os.getenv('USE_X_SETTINGS'):
        print ("USE_X_SETTINGS is ENABLED\n")
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1, x_host=1)

    s_type = socket.AF_INET6 if ipv6_enabled else socket.AF_INET

    if ssl_mode:
        # @todo finalise SSL config, but this should get you in the right direction if you need it.
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen((host, port), s_type),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen((host, int(port)), s_type), app)

    if is_graceful_shutdown:
        print('Gracefully exited')
