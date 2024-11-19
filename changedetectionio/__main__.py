from flask import Flask
from changedetectionio.strtobool import strtobool
from json.decoder import JSONDecodeError
import os
os.environ['EVENTLET_NO_GREENDNS'] = 'yes'
import eventlet
import eventlet.wsgi
import getopt
import signal
import socket
import sys

from changedetectionio import store
from changedetectionio.flask_app import changedetection_app
from loguru import logger

from . import __version__


# Parent wrapper or OS sends us a SIGTERM/SIGINT, do everything required for a clean shutdown
class SigShutdownHandler(object):
    def __init__(self, app):
        self.app = app
        signal.signal(signal.SIGTERM, lambda _signum, _frame: self._signal_handler("SIGTERM"))
        signal.signal(signal.SIGINT, lambda _signum, _frame: self._signal_handler("SIGINT"))

    def _signal_handler(self, signame):
        logger.critical(f'Shutdown: Got Signal - {signame}, Saving DB to disk and calling shutdown')
        datastore = self.app.config["DATASTORE"]
        datastore.sync_to_json()
        logger.success('Sync JSON to disk complete.')
        # This will throw a SystemExit exception, because eventlet.wsgi.server doesn't know how to deal with it.
        # Solution: move to gevent or other server in the future (#2014)
        datastore.stop_thread = True
        self.app.config.exit.set()
        sys.exit(0)

def create_application() -> Flask:
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
        log_level_for_stdout = { 'DEBUG', 'SUCCESS' }
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
        raise(e)

    app = changedetection_app(app_config, datastore)

    sigshutdown_handler = SigShutdownHandler(app)

    # Go into cleanup mode
    if do_cleanup:
        datastore.remove_unused_snapshots()

    app.config['datastore_path'] = datastore_path


    @app.context_processor
    def inject_version():
        return dict(right_sticky="v{}".format(datastore.data['version_tag']),
                    new_version_available=app.config['NEW_VERSION_AVAILABLE'],
                    has_password=datastore.data['settings']['application']['password'] is not False
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
        logger.info("USE_X_SETTINGS is ENABLED")
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_prefix=1, x_host=1)

    app.config["USE_IPV6"] = ipv6_enabled
    app.config["USE_SSL"] = ssl_mode
    app.config["HOST"] = host
    app.config["PORT"] = port

    return app

app = create_application()

def main():
    from .__main__ import app
    s_type = socket.AF_INET6 if app.config["USE_IPV6"] else socket.AF_INET

    host = app.config["HOST"]
    port = app.config["PORT"]

    if app.config["USE_SSL"]:
        # @todo finalise SSL config, but this should get you in the right direction if you need it.
        eventlet.wsgi.server(eventlet.wrap_ssl(eventlet.listen((host, port), s_type),
                                               certfile='cert.pem',
                                               keyfile='privkey.pem',
                                               server_side=True), app)

    else:
        eventlet.wsgi.server(eventlet.listen((host, int(port)), s_type), app)

if __name__ == "__main__":
    main()
