#!/usr/bin/python3

# Launch as a eventlet.wsgi server instance.

import getopt
import os
import signal
import sys

import eventlet
import eventlet.wsgi
from . import store, changedetection_app, content_fetcher
from . import __version__

# Only global so we can access it in the signal handler
datastore = None
app = None

def sigterm_handler(_signo, _stack_frame):
    global app
    global datastore
#    app.config.exit.set()
    print('Shutdown: Got SIGTERM, DB saved to disk')
    datastore.sync_to_json()
#    raise SystemExit

def main():
    global datastore
    global app
    ssl_mode = False
    host = ''
    port = os.environ.get('PORT') or 5000
    do_cleanup = False
    datastore_path = None

    # On Windows, create and use a default path.
    if os.name == 'nt':
        datastore_path = os.path.expandvars(r'%APPDATA%\changedetection.io')
        os.makedirs(datastore_path, exist_ok=True)
    else:
        # Must be absolute so that send_from_directory doesnt try to make it relative to backend/
        datastore_path = os.path.join(os.getcwd(), "../datastore")

    try:
        opts, args = getopt.getopt(sys.argv[1:], "Ccsd:h:p:", "port")
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


    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], version_tag=__version__)
    app = changedetection_app(app_config, datastore)

    signal.signal(signal.SIGTERM, sigterm_handler)

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

    if ssl_mode:
        # @todo finalise SSL config, but this should get you in the right direction if you need it.
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen((host, port)),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen((host, int(port))), app)

