#!/usr/bin/env python3

import flask_login
import locale
import os
import queue
import sys
import threading
import time
import timeago
from blinker import signal

from changedetectionio.strtobool import strtobool
from threading import Event
from changedetectionio.custom_queue import SignalPriorityQueue, AsyncSignalPriorityQueue
from changedetectionio import worker_handler

from flask import (
    Flask,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_compress import Compress as FlaskCompress
from flask_login import current_user
from flask_restful import abort, Api
from flask_cors import CORS

# Create specific signals for application events
# Make this a global singleton to avoid multiple signal objects
watch_check_update = signal('watch_check_update', doc='Signal sent when a watch check is completed')
from flask_wtf import CSRFProtect
from loguru import logger

from changedetectionio import __version__
from changedetectionio import queuedWatchMetaData
from changedetectionio.api import Watch, WatchHistory, WatchSingleHistory, CreateWatch, Import, SystemInfo, Tag, Tags, Notifications
from changedetectionio.api.Search import Search
from .time_handler import is_within_schedule

datastore = None

# Local
ticker_thread = None
extra_stylesheets = []

# Use async queue by default, keep sync for backward compatibility  
update_q = AsyncSignalPriorityQueue() if worker_handler.USE_ASYNC_WORKERS else SignalPriorityQueue()
notification_q = queue.Queue()
MAX_QUEUE_SIZE = 2000

app = Flask(__name__,
            static_url_path="",
            static_folder="static",
            template_folder="templates")

# Will be initialized in changedetection_app
socketio_server = None

# Enable CORS, especially useful for the Chrome extension to operate from anywhere
CORS(app)

# Super handy for compressing large BrowserSteps responses and others
FlaskCompress(app)

# Stop browser caching of assets
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config.exit = Event()

app.config['NEW_VERSION_AVAILABLE'] = False

if os.getenv('FLASK_SERVER_NAME'):
    app.config['SERVER_NAME'] = os.getenv('FLASK_SERVER_NAME')

#app.config["EXPLAIN_TEMPLATE_LOADING"] = True

# Disables caching of the templates
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.add_extension('jinja2.ext.loopcontrols')
csrf = CSRFProtect()
csrf.init_app(app)
notification_debug_log=[]

# Locale for correct presentation of prices etc
default_locale = locale.getdefaultlocale()
logger.info(f"System locale default is {default_locale}")
try:
    locale.setlocale(locale.LC_ALL, default_locale)
except locale.Error:
    logger.warning(f"Unable to set locale {default_locale}, locale is not installed maybe?")

watch_api = Api(app, decorators=[csrf.exempt])

def init_app_secret(datastore_path):
    secret = ""

    path = "{}/secret.txt".format(datastore_path)

    try:
        with open(path, "r") as f:
            secret = f.read()

    except FileNotFoundError:
        import secrets
        with open(path, "w") as f:
            secret = secrets.token_hex(32)
            f.write(secret)

    return secret


@app.template_global()
def get_darkmode_state():
    css_dark_mode = request.cookies.get('css_dark_mode', 'false')
    return 'true' if css_dark_mode and strtobool(css_dark_mode) else 'false'

@app.template_global()
def get_css_version():
    return __version__

@app.template_global()
def get_socketio_path():
    """Generate the correct Socket.IO path prefix for the client"""
    # If behind a proxy with a sub-path, we need to respect that path
    prefix = ""
    if os.getenv('USE_X_SETTINGS') and 'X-Forwarded-Prefix' in request.headers:
        prefix = request.headers['X-Forwarded-Prefix']

    # Socket.IO will be available at {prefix}/socket.io/
    return prefix


@app.template_filter('format_number_locale')
def _jinja2_filter_format_number_locale(value: float) -> str:
    "Formats for example 4000.10 to the local locale default of 4,000.10"
    # Format the number with two decimal places (locale format string will return 6 decimal)
    formatted_value = locale.format_string("%.2f", value, grouping=True)

    return formatted_value

@app.template_global('is_checking_now')
def _watch_is_checking_now(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    return worker_handler.is_watch_running(watch_obj['uuid'])

@app.template_global('get_watch_queue_position')
def _get_watch_queue_position(watch_obj):
    """Get the position of a watch in the queue"""
    uuid = watch_obj['uuid']
    return update_q.get_uuid_position(uuid)

@app.template_global('get_current_worker_count')
def _get_current_worker_count():
    """Get the current number of operational workers"""
    return worker_handler.get_worker_count()

@app.template_global('get_worker_status_info')
def _get_worker_status_info():
    """Get detailed worker status information for display"""
    status = worker_handler.get_worker_status()
    running_uuids = worker_handler.get_running_uuids()
    
    return {
        'count': status['worker_count'],
        'type': status['worker_type'],
        'active_workers': len(running_uuids),
        'processing_watches': running_uuids,
        'loop_running': status.get('async_loop_running', None)
    }


# We use the whole watch object from the store/JSON so we can see if there's some related status in terms of a thread
# running or something similar.
@app.template_filter('format_last_checked_time')
def _jinja2_filter_datetime(watch_obj, format="%Y-%m-%d %H:%M:%S"):

    if watch_obj['last_checked'] == 0:
        return 'Not yet'

    return timeago.format(int(watch_obj['last_checked']), time.time())

@app.template_filter('format_timestamp_timeago')
def _jinja2_filter_datetimestamp(timestamp, format="%Y-%m-%d %H:%M:%S"):
    if not timestamp:
        return 'Not yet'

    return timeago.format(int(timestamp), time.time())


@app.template_filter('pagination_slice')
def _jinja2_filter_pagination_slice(arr, skip):
    per_page = datastore.data['settings']['application'].get('pager_size', 50)
    if per_page:
        return arr[skip:skip + per_page]

    return arr

@app.template_filter('format_seconds_ago')
def _jinja2_filter_seconds_precise(timestamp):
    if timestamp == False:
        return 'Not yet'

    return format(int(time.time()-timestamp), ',d')

# Import login_optionally_required from auth_decorator
from changedetectionio.auth_decorator import login_optionally_required

# When nobody is logged in Flask-Login's current_user is set to an AnonymousUser object.
class User(flask_login.UserMixin):
    id=None

    def set_password(self, password):
        return True
    def get_user(self, email="defaultuser@changedetection.io"):
        return self
    def is_authenticated(self):
        return True
    def is_active(self):
        return True
    def is_anonymous(self):
        return False
    def get_id(self):
        return str(self.id)

    # Compare given password against JSON store or Env var
    def check_password(self, password):
        import base64
        import hashlib

        # Can be stored in env (for deployments) or in the general configs
        raw_salt_pass = os.getenv("SALTED_PASS", False)

        if not raw_salt_pass:
            raw_salt_pass = datastore.data['settings']['application'].get('password')

        raw_salt_pass = base64.b64decode(raw_salt_pass)
        salt_from_storage = raw_salt_pass[:32]  # 32 is the length of the salt

        # Use the exact same setup you used to generate the key, but this time put in the password to check
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),  # Convert the password to bytes
            salt_from_storage,
            100000
        )
        new_key = salt_from_storage + new_key

        return new_key == raw_salt_pass

    pass


def changedetection_app(config=None, datastore_o=None):
    logger.trace("TRACE log is enabled")

    global datastore, socketio_server
    datastore = datastore_o

    # so far just for read-only via tests, but this will be moved eventually to be the main source
    # (instead of the global var)
    app.config['DATASTORE'] = datastore_o
    
    # Store the signal in the app config to ensure it's accessible everywhere
    app.config['watch_check_update_SIGNAL'] = watch_check_update

    login_manager = flask_login.LoginManager(app)
    login_manager.login_view = 'login'
    app.secret_key = init_app_secret(config['datastore_path'])
    
    # Set up a request hook to check authentication for all routes
    @app.before_request
    def check_authentication():
        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)

        if has_password_enabled and not flask_login.current_user.is_authenticated:
            # Permitted
            if request.endpoint and request.endpoint == 'static_content' and request.view_args:
                # Handled by static_content handler
                return None
            # Permitted
            elif request.endpoint and 'login' in request.endpoint:
                return None
            elif request.endpoint and 'diff_history_page' in request.endpoint and datastore.data['settings']['application'].get('shared_diff_access'):
                return None
            elif request.method in flask_login.config.EXEMPT_METHODS:
                return None
            elif app.config.get('LOGIN_DISABLED'):
                return None
            # RSS access with token is allowed
            elif request.endpoint and 'rss.feed' in request.endpoint:
                return None
            # Socket.IO routes - need separate handling
            elif request.path.startswith('/socket.io/'):
                return None
            # API routes - use their own auth mechanism (@auth.check_token)
            elif request.path.startswith('/api/'):
                return None
            else:
                return login_manager.unauthorized()


    watch_api.add_resource(WatchSingleHistory,
                           '/api/v1/watch/<string:uuid>/history/<string:timestamp>',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(WatchHistory,
                           '/api/v1/watch/<string:uuid>/history',
                           resource_class_kwargs={'datastore': datastore})

    watch_api.add_resource(CreateWatch, '/api/v1/watch',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(Watch, '/api/v1/watch/<string:uuid>',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(SystemInfo, '/api/v1/systeminfo',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(Import,
                           '/api/v1/import',
                           resource_class_kwargs={'datastore': datastore})

    watch_api.add_resource(Tags, '/api/v1/tags',
                           resource_class_kwargs={'datastore': datastore})

    watch_api.add_resource(Tag, '/api/v1/tag', '/api/v1/tag/<string:uuid>',
                           resource_class_kwargs={'datastore': datastore})
                           
    watch_api.add_resource(Search, '/api/v1/search',
                           resource_class_kwargs={'datastore': datastore})

    watch_api.add_resource(Notifications, '/api/v1/notifications',
                           resource_class_kwargs={'datastore': datastore})

    @login_manager.user_loader
    def user_loader(email):
        user = User()
        user.get_user(email)
        return user

    @login_manager.unauthorized_handler
    def unauthorized_handler():
        flash("You must be logged in, please log in.", 'error')
        return redirect(url_for('login', next=url_for('watchlist.index')))

    @app.route('/logout')
    def logout():
        flask_login.logout_user()
        return redirect(url_for('watchlist.index'))

    # https://github.com/pallets/flask/blob/93dd1709d05a1cf0e886df6223377bdab3b077fb/examples/tutorial/flaskr/__init__.py#L39
    # You can divide up the stuff like this
    @app.route('/login', methods=['GET', 'POST'])
    def login():

        if request.method == 'GET':
            if flask_login.current_user.is_authenticated:
                flash("Already logged in")
                return redirect(url_for("watchlist.index"))

            output = render_template("login.html")
            return output

        user = User()
        user.id = "defaultuser@changedetection.io"

        password = request.form.get('password')

        if (user.check_password(password)):
            flask_login.login_user(user, remember=True)

            # For now there's nothing else interesting here other than the index/list page
            # It's more reliable and safe to ignore the 'next' redirect
            # When we used...
            # next = request.args.get('next')
            # return redirect(next or url_for('watchlist.index'))
            # We would sometimes get login loop errors on sites hosted in sub-paths

            # note for the future:
            #            if not is_safe_url(next):
            #                return flask.abort(400)
            return redirect(url_for('watchlist.index'))

        else:
            flash('Incorrect password', 'error')

        return redirect(url_for('login'))

    @app.before_request
    def before_request_handle_cookie_x_settings():
        # Set the auth cookie path if we're running as X-settings/X-Forwarded-Prefix
        if os.getenv('USE_X_SETTINGS') and 'X-Forwarded-Prefix' in request.headers:
            app.config['REMEMBER_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']
            app.config['SESSION_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']
        return None

    @app.route("/static/<string:group>/<string:filename>", methods=['GET'])
    def static_content(group, filename):
        from flask import make_response
        import re
        group = re.sub(r'[^\w.-]+', '', group.lower())
        filename = re.sub(r'[^\w.-]+', '', filename.lower())

        if group == 'screenshot':
            # Could be sensitive, follow password requirements
            if datastore.data['settings']['application']['password'] and not flask_login.current_user.is_authenticated:
                if not datastore.data['settings']['application'].get('shared_diff_access'):
                    abort(403)

            screenshot_filename = "last-screenshot.png" if not request.args.get('error_screenshot') else "last-error-screenshot.png"

            # These files should be in our subdirectory
            try:
                # set nocache, set content-type
                response = make_response(send_from_directory(os.path.join(datastore_o.datastore_path, filename), screenshot_filename))
                response.headers['Content-type'] = 'image/png'
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = 0
                return response

            except FileNotFoundError:
                abort(404)


        if group == 'visual_selector_data':
            # Could be sensitive, follow password requirements
            if datastore.data['settings']['application']['password'] and not flask_login.current_user.is_authenticated:
                abort(403)

            # These files should be in our subdirectory
            try:
                # set nocache, set content-type,
                # `filename` is actually directory UUID of the watch
                watch_directory = str(os.path.join(datastore_o.datastore_path, filename))
                response = None
                if os.path.isfile(os.path.join(watch_directory, "elements.deflate")):
                    response = make_response(send_from_directory(watch_directory, "elements.deflate"))
                    response.headers['Content-Type'] = 'application/json'
                    response.headers['Content-Encoding'] = 'deflate'
                else:
                    logger.error(f'Request elements.deflate at "{watch_directory}" but was not found.')
                    abort(404)

                if response:
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response.headers['Pragma'] = 'no-cache'
                    response.headers['Expires'] = "0"

                return response

            except FileNotFoundError:
                abort(404)

        # These files should be in our subdirectory
        try:
            return send_from_directory(f"static/{group}", path=filename)
        except FileNotFoundError:
            abort(404)


    import changedetectionio.blueprint.browser_steps as browser_steps
    app.register_blueprint(browser_steps.construct_blueprint(datastore), url_prefix='/browser-steps')

    from changedetectionio.blueprint.imports import construct_blueprint as construct_import_blueprint
    app.register_blueprint(construct_import_blueprint(datastore, update_q, queuedWatchMetaData), url_prefix='/imports')

    import changedetectionio.blueprint.price_data_follower as price_data_follower
    app.register_blueprint(price_data_follower.construct_blueprint(datastore, update_q), url_prefix='/price_data_follower')

    import changedetectionio.blueprint.tags as tags
    app.register_blueprint(tags.construct_blueprint(datastore), url_prefix='/tags')

    import changedetectionio.blueprint.check_proxies as check_proxies
    app.register_blueprint(check_proxies.construct_blueprint(datastore=datastore), url_prefix='/check_proxy')

    import changedetectionio.blueprint.backups as backups
    app.register_blueprint(backups.construct_blueprint(datastore), url_prefix='/backups')

    import changedetectionio.blueprint.settings as settings
    app.register_blueprint(settings.construct_blueprint(datastore), url_prefix='/settings')

    import changedetectionio.conditions.blueprint as conditions
    app.register_blueprint(conditions.construct_blueprint(datastore), url_prefix='/conditions')

    import changedetectionio.blueprint.rss.blueprint as rss
    app.register_blueprint(rss.construct_blueprint(datastore), url_prefix='/rss')

    # watchlist UI buttons etc
    import changedetectionio.blueprint.ui as ui
    app.register_blueprint(ui.construct_blueprint(datastore, update_q, worker_handler, queuedWatchMetaData, watch_check_update))

    import changedetectionio.blueprint.watchlist as watchlist
    app.register_blueprint(watchlist.construct_blueprint(datastore=datastore, update_q=update_q, queuedWatchMetaData=queuedWatchMetaData), url_prefix='')

    # Initialize Socket.IO server conditionally based on settings
    socket_io_enabled = datastore.data['settings']['application']['ui'].get('socket_io_enabled', True)
    if socket_io_enabled:
        from changedetectionio.realtime.socket_server import init_socketio
        global socketio_server
        socketio_server = init_socketio(app, datastore)
        logger.info("Socket.IO server initialized")
    else:
        logger.info("Socket.IO server disabled via settings")
        socketio_server = None

    # Memory cleanup endpoint
    @app.route('/gc-cleanup', methods=['GET'])
    @login_optionally_required
    def gc_cleanup():
        from changedetectionio.gc_cleanup import memory_cleanup
        from flask import jsonify

        result = memory_cleanup(app)
        return jsonify({"status": "success", "message": "Memory cleanup completed", "result": result})

    # Worker health check endpoint
    @app.route('/worker-health', methods=['GET'])
    @login_optionally_required
    def worker_health():
        from flask import jsonify
        
        expected_workers = int(os.getenv("FETCH_WORKERS", datastore.data['settings']['requests']['workers']))
        
        # Get basic status
        status = worker_handler.get_worker_status()
        
        # Perform health check
        health_result = worker_handler.check_worker_health(
            expected_count=expected_workers,
            update_q=update_q,
            notification_q=notification_q,
            app=app,
            datastore=datastore
        )
        
        return jsonify({
            "status": "success",
            "worker_status": status,
            "health_check": health_result,
            "expected_workers": expected_workers
        })

    # Queue status endpoint
    @app.route('/queue-status', methods=['GET'])
    @login_optionally_required
    def queue_status():
        from flask import jsonify, request
        
        # Get specific UUID position if requested
        target_uuid = request.args.get('uuid')
        
        if target_uuid:
            position_info = update_q.get_uuid_position(target_uuid)
            return jsonify({
                "status": "success",
                "uuid": target_uuid,
                "queue_position": position_info
            })
        else:
            # Get pagination parameters
            limit = request.args.get('limit', type=int)
            offset = request.args.get('offset', type=int, default=0)
            summary_only = request.args.get('summary', type=bool, default=False)
            
            if summary_only:
                # Fast summary for large queues
                summary = update_q.get_queue_summary()
                return jsonify({
                    "status": "success",
                    "queue_summary": summary
                })
            else:
                # Get queued items with pagination support
                if limit is None:
                    # Default limit for large queues to prevent performance issues
                    queue_size = update_q.qsize()
                    if queue_size > 100:
                        limit = 50
                        logger.warning(f"Large queue ({queue_size} items) detected, limiting to {limit} items. Use ?limit=N for more.")
                
                all_queued = update_q.get_all_queued_uuids(limit=limit, offset=offset)
                return jsonify({
                    "status": "success",
                    "queue_size": update_q.qsize(),
                    "queued_data": all_queued
                })

    # Start the async workers during app initialization
    # Can be overridden by ENV or use the default settings
    n_workers = int(os.getenv("FETCH_WORKERS", datastore.data['settings']['requests']['workers']))
    logger.info(f"Starting {n_workers} workers during app initialization")
    worker_handler.start_workers(n_workers, update_q, notification_q, app, datastore)

    # @todo handle ctrl break
    ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks).start()
    threading.Thread(target=notification_runner).start()

    in_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    # Check for new release version, but not when running in test/build or pytest
    if not os.getenv("GITHUB_REF", False) and not strtobool(os.getenv('DISABLE_VERSION_CHECK', 'no')) and not in_pytest:
        threading.Thread(target=check_for_new_version).start()

    # Return the Flask app - the Socket.IO will be attached to it but initialized separately
    # This avoids circular dependencies
    return app


# Check for new version and anonymous stats
def check_for_new_version():
    import requests
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    while not app.config.exit.is_set():
        try:
            r = requests.post("https://changedetection.io/check-ver.php",
                              data={'version': __version__,
                                    'app_guid': datastore.data['app_guid'],
                                    'watch_count': len(datastore.data['watching'])
                                    },

                              verify=False)
        except:
            pass

        try:
            if "new_version" in r.text:
                app.config['NEW_VERSION_AVAILABLE'] = True
        except:
            pass

        # Check daily
        app.config.exit.wait(86400)


def notification_runner():
    global notification_debug_log
    from datetime import datetime
    import json
    with app.app_context():
        while not app.config.exit.is_set():
            try:
                # At the moment only one thread runs (single runner)
                n_object = notification_q.get(block=False)
            except queue.Empty:
                time.sleep(1)

            else:

                now = datetime.now()
                sent_obj = None

                try:
                    from changedetectionio.notification.handler import process_notification

                    # Fallback to system config if not set
                    if not n_object.get('notification_body') and datastore.data['settings']['application'].get('notification_body'):
                        n_object['notification_body'] = datastore.data['settings']['application'].get('notification_body')

                    if not n_object.get('notification_title') and datastore.data['settings']['application'].get('notification_title'):
                        n_object['notification_title'] = datastore.data['settings']['application'].get('notification_title')

                    if not n_object.get('notification_format') and datastore.data['settings']['application'].get('notification_format'):
                        n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')
                    if n_object.get('notification_urls', {}):
                        sent_obj = process_notification(n_object, datastore)

                except Exception as e:
                    logger.error(f"Watch URL: {n_object['watch_url']}  Error {str(e)}")

                    # UUID wont be present when we submit a 'test' from the global settings
                    if 'uuid' in n_object:
                        datastore.update_watch(uuid=n_object['uuid'],
                                               update_obj={'last_notification_error': "Notification error detected, goto notification log."})

                    log_lines = str(e).splitlines()
                    notification_debug_log += log_lines

                    with app.app_context():
                        app.config['watch_check_update_SIGNAL'].send(app_context=app, watch_uuid=n_object.get('uuid'))

                # Process notifications
                notification_debug_log+= ["{} - SENDING - {}".format(now.strftime("%Y/%m/%d %H:%M:%S,000"), json.dumps(sent_obj))]
                # Trim the log length
                notification_debug_log = notification_debug_log[-100:]



# Threaded runner, look for new watches to feed into the Queue.
def ticker_thread_check_time_launch_checks():
    import random
    proxy_last_called_time = {}
    last_health_check = 0

    recheck_time_minimum_seconds = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3))
    logger.debug(f"System env MINIMUM_SECONDS_RECHECK_TIME {recheck_time_minimum_seconds}")

    # Workers are now started during app initialization, not here

    while not app.config.exit.is_set():

        # Periodic worker health check (every 60 seconds)
        now = time.time()
        if now - last_health_check > 60:
            expected_workers = int(os.getenv("FETCH_WORKERS", datastore.data['settings']['requests']['workers']))
            health_result = worker_handler.check_worker_health(
                expected_count=expected_workers,
                update_q=update_q,
                notification_q=notification_q,
                app=app,
                datastore=datastore
            )
            
            if health_result['status'] != 'healthy':
                logger.warning(f"Worker health check: {health_result['message']}")
                
            last_health_check = now

        # Get a list of watches by UUID that are currently fetching data
        running_uuids = worker_handler.get_running_uuids()

        # Re #232 - Deepcopy the data incase it changes while we're iterating through it all
        watch_uuid_list = []
        while True:
            try:
                # Get a list of watches sorted by last_checked, [1] because it gets passed a tuple
                # This is so we examine the most over-due first
                for k in sorted(datastore.data['watching'].items(), key=lambda item: item[1].get('last_checked',0)):
                    watch_uuid_list.append(k[0])

            except RuntimeError as e:
                # RuntimeError: dictionary changed size during iteration
                time.sleep(0.1)
                watch_uuid_list = []
            else:
                break

        # Re #438 - Don't place more watches in the queue to be checked if the queue is already large
        while update_q.qsize() >= 2000:
            logger.warning(f"Recheck watches queue size limit reached ({MAX_QUEUE_SIZE}), skipping adding more items")
            time.sleep(3)


        recheck_time_system_seconds = int(datastore.threshold_seconds)

        # Check for watches outside of the time threshold to put in the thread queue.
        for uuid in watch_uuid_list:
            now = time.time()
            watch = datastore.data['watching'].get(uuid)
            if not watch:
                logger.error(f"Watch: {uuid} no longer present.")
                continue

            # No need todo further processing if it's paused
            if watch['paused']:
                continue

            # @todo - Maybe make this a hook?
            # Time schedule limit - Decide between watch or global settings
            if watch.get('time_between_check_use_default'):
                time_schedule_limit = datastore.data['settings']['requests'].get('time_schedule_limit', {})
                logger.trace(f"{uuid} Time scheduler - Using system/global settings")
            else:
                time_schedule_limit = watch.get('time_schedule_limit')
                logger.trace(f"{uuid} Time scheduler - Using watch settings (not global settings)")
            tz_name = datastore.data['settings']['application'].get('timezone', 'UTC')

            if time_schedule_limit and time_schedule_limit.get('enabled'):
                try:
                    result = is_within_schedule(time_schedule_limit=time_schedule_limit,
                                                default_tz=tz_name
                                                )
                    if not result:
                        logger.trace(f"{uuid} Time scheduler - not within schedule skipping.")
                        continue
                except Exception as e:
                    logger.error(
                        f"{uuid} - Recheck scheduler, error handling timezone, check skipped - TZ name '{tz_name}' - {str(e)}")
                    return False
            # If they supplied an individual entry minutes to threshold.
            threshold = recheck_time_system_seconds if watch.get('time_between_check_use_default') else watch.threshold_seconds()

            # #580 - Jitter plus/minus amount of time to make the check seem more random to the server
            jitter = datastore.data['settings']['requests'].get('jitter_seconds', 0)
            if jitter > 0:
                if watch.jitter_seconds == 0:
                    watch.jitter_seconds = random.uniform(-abs(jitter), jitter)

            seconds_since_last_recheck = now - watch['last_checked']

            if seconds_since_last_recheck >= (threshold + watch.jitter_seconds) and seconds_since_last_recheck >= recheck_time_minimum_seconds:
                if not uuid in running_uuids and uuid not in [q_uuid.item['uuid'] for q_uuid in update_q.queue]:

                    # Proxies can be set to have a limit on seconds between which they can be called
                    watch_proxy = datastore.get_preferred_proxy_for_watch(uuid=uuid)
                    if watch_proxy and watch_proxy in list(datastore.proxy_list.keys()):
                        # Proxy may also have some threshold minimum
                        proxy_list_reuse_time_minimum = int(datastore.proxy_list.get(watch_proxy, {}).get('reuse_time_minimum', 0))
                        if proxy_list_reuse_time_minimum:
                            proxy_last_used_time = proxy_last_called_time.get(watch_proxy, 0)
                            time_since_proxy_used = int(time.time() - proxy_last_used_time)
                            if time_since_proxy_used < proxy_list_reuse_time_minimum:
                                # Not enough time difference reached, skip this watch
                                logger.debug(f"> Skipped UUID {uuid} "
                                        f"using proxy '{watch_proxy}', not "
                                        f"enough time between proxy requests "
                                        f"{time_since_proxy_used}s/{proxy_list_reuse_time_minimum}s")
                                continue
                            else:
                                # Record the last used time
                                proxy_last_called_time[watch_proxy] = int(time.time())

                    # Use Epoch time as priority, so we get a "sorted" PriorityQueue, but we can still push a priority 1 into it.
                    priority = int(time.time())
                    logger.debug(
                        f"> Queued watch UUID {uuid} "
                        f"last checked at {watch['last_checked']} "
                        f"queued at {now:0.2f} priority {priority} "
                        f"jitter {watch.jitter_seconds:0.2f}s, "
                        f"{now - watch['last_checked']:0.2f}s since last checked")

                    # Into the queue with you
                    worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=priority, item={'uuid': uuid}))

                    # Reset for next time
                    watch.jitter_seconds = 0

        # Wait before checking the list again - saves CPU
        time.sleep(1)

        # Should be low so we can break this out in testing
        app.config.exit.wait(1)
