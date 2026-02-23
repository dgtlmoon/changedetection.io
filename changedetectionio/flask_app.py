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
from pathlib import Path

from changedetectionio.strtobool import strtobool
from threading import Event
from changedetectionio.queue_handlers import RecheckPriorityQueue, NotificationQueue
from changedetectionio import worker_pool
import changedetectionio.llm as llm

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from flask_restful import abort, Api
from flask_cors import CORS

# Create specific signals for application events
# Make this a global singleton to avoid multiple signal objects
watch_check_update = signal('watch_check_update', doc='Signal sent when a watch check is completed')
from flask_wtf import CSRFProtect
from flask_babel import Babel, gettext, get_locale
from loguru import logger

from changedetectionio import __version__
from changedetectionio import queuedWatchMetaData
from changedetectionio.api import Watch, WatchHistory, WatchSingleHistory, WatchHistoryDiff, CreateWatch, Import, SystemInfo, Tag, Tags, Notifications, WatchFavicon
from changedetectionio.api.Search import Search
from .time_handler import is_within_schedule
from changedetectionio.languages import get_available_languages, get_language_codes, get_flag_for_locale, get_timeago_locale
from changedetectionio.favicon_utils import get_favicon_mime_type

IN_PYTEST = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ

datastore = None

# Local
ticker_thread = None
extra_stylesheets = []

# Use bulletproof janus-based queues for sync/async reliability  
update_q = RecheckPriorityQueue()
notification_q = NotificationQueue()
llm_summary_q = llm.create_queue()
MAX_QUEUE_SIZE = 5000

app = Flask(__name__,
            static_url_path="",
            static_folder="static",
            template_folder="templates")

# Will be initialized in changedetection_app
socketio_server = None

# Enable CORS, especially useful for the Chrome extension to operate from anywhere
CORS(app)

# Flask-Compress handles HTTP compression, Socket.IO compression disabled to prevent memory leak.
# There's also a bug between flask compress and socketio that causes some kind of slow memory leak
# It's better to use compression on your reverse proxy (nginx etc) instead.
if strtobool(os.getenv("FLASK_ENABLE_COMPRESSION")):
    from flask_compress import Compress as FlaskCompress
    app.config['COMPRESS_MIN_SIZE'] = 2096
    app.config['COMPRESS_MIMETYPES'] = ['text/html', 'text/css', 'text/javascript', 'application/json', 'application/javascript', 'image/svg+xml']
    # Use gzip only - smaller memory footprint than zstd/brotli (4-8KB vs 200-500KB contexts)
    app.config['COMPRESS_ALGORITHM'] = ['gzip']
    compress = FlaskCompress()
    compress.init_app(app)

app.config['TEMPLATES_AUTO_RELOAD'] = False


# Stop browser caching of assets
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config.exit = Event()

app.config['NEW_VERSION_AVAILABLE'] = False

if os.getenv('FLASK_SERVER_NAME'):
    app.config['SERVER_NAME'] = os.getenv('FLASK_SERVER_NAME')

# Babel/i18n configuration
app.config['BABEL_TRANSLATION_DIRECTORIES'] = str(Path(__file__).parent / 'translations')
app.config['BABEL_DEFAULT_LOCALE'] = 'en_GB'

# Session configuration
# NOTE: Flask session (for locale, etc.) is separate from Flask-Login's remember-me cookie
# - Flask session stores data like session['locale'] in a signed cookie
# - Flask-Login's remember=True creates a separate authentication cookie
# - Setting PERMANENT_SESSION_LIFETIME controls how long the Flask session cookie lasts
from datetime import timedelta
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=3650)  # ~10 years (effectively unlimited)

#app.config["EXPLAIN_TEMPLATE_LOADING"] = True


app.jinja_env.add_extension('jinja2.ext.loopcontrols')

# Configure Jinja2 to search for templates in plugin directories
def _configure_plugin_templates():
    """Configure Jinja2 loader to include plugin template directories."""
    from jinja2 import ChoiceLoader, FileSystemLoader
    from changedetectionio.pluggy_interface import get_plugin_template_paths

    # Get plugin template paths
    plugin_template_paths = get_plugin_template_paths()

    if plugin_template_paths:
        # Create a ChoiceLoader that searches app templates first, then plugin templates
        loaders = [app.jinja_loader]  # Keep the default app loader first
        for path in plugin_template_paths:
            loaders.append(FileSystemLoader(path))

        app.jinja_loader = ChoiceLoader(loaders)
        logger.info(f"Configured Jinja2 to search {len(plugin_template_paths)} plugin template directories")

# Configure plugin templates (called after plugins are loaded)
_configure_plugin_templates()
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

    path = os.path.join(datastore_path, "secret.txt")

    try:
        with open(path, "r", encoding='utf-8') as f:
            secret = f.read()

    except FileNotFoundError:
        import secrets
        with open(path, "w", encoding='utf-8') as f:
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

@app.template_global('is_safe_valid_url')
def _is_safe_valid_url(test_url):
    from .validate_url import is_safe_valid_url
    return is_safe_valid_url(test_url)


@app.template_filter('format_number_locale')
def _jinja2_filter_format_number_locale(value: float) -> str:
    "Formats for example 4000.10 to the local locale default of 4,000.10"
    # Format the number with two decimal places (locale format string will return 6 decimal)
    formatted_value = locale.format_string("%.2f", value, grouping=True)

    return formatted_value

@app.template_global('is_checking_now')
def _watch_is_checking_now(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    return worker_pool.is_watch_running(watch_obj['uuid'])

@app.template_global('get_watch_queue_position')
def _get_watch_queue_position(watch_obj):
    """Get the position of a watch in the queue"""
    uuid = watch_obj['uuid']
    return update_q.get_uuid_position(uuid)

@app.template_global('get_current_worker_count')
def _get_current_worker_count():
    """Get the current number of operational workers"""
    return worker_pool.get_worker_count()

@app.template_global('get_worker_status_info')
def _get_worker_status_info():
    """Get detailed worker status information for display"""
    status = worker_pool.get_worker_status()
    running_uuids = worker_pool.get_running_uuids()
    
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
        return gettext('Not yet')

    locale = get_timeago_locale(str(get_locale()))
    try:
        return timeago.format(int(watch_obj['last_checked']), time.time(), locale)
    except:
        # Fallback to English if locale not supported by timeago
        return timeago.format(int(watch_obj['last_checked']), time.time(), 'en')

@app.template_filter('format_timestamp_timeago')
def _jinja2_filter_datetimestamp(timestamp, format="%Y-%m-%d %H:%M:%S"):
    if not timestamp:
        return gettext('Not yet')

    locale = get_timeago_locale(str(get_locale()))
    try:
        return timeago.format(int(timestamp), time.time(), locale)
    except:
        # Fallback to English if locale not supported by timeago
        return timeago.format(int(timestamp), time.time(), 'en')


@app.template_filter('pagination_slice')
def _jinja2_filter_pagination_slice(arr, skip):
    per_page = datastore.data['settings']['application'].get('pager_size', 50)
    if per_page:
        return arr[skip:skip + per_page]

    return arr

@app.template_filter('format_seconds_ago')
def _jinja2_filter_seconds_precise(timestamp):
    if timestamp == False:
        return gettext('Not yet')

    return format(int(time.time()-timestamp), ',d')

@app.template_filter('format_duration')
def _jinja2_filter_format_duration(seconds):
    """Format a duration in seconds into human readable string like '5 days, 3 hours, 30 minutes'"""
    from datetime import timedelta

    if not seconds or seconds < 0:
        return gettext('0 seconds')

    td = timedelta(seconds=int(seconds))

    # Calculate components
    years = td.days // 365
    remaining_days = td.days % 365
    months = remaining_days // 30
    remaining_days = remaining_days % 30
    weeks = remaining_days // 7
    days = remaining_days % 7

    hours = td.seconds // 3600
    minutes = (td.seconds % 3600) // 60
    secs = td.seconds % 60

    # Build parts list
    parts = []
    if years > 0:
        parts.append(f"{years} {gettext('year') if years == 1 else gettext('years')}")
    if months > 0:
        parts.append(f"{months} {gettext('month') if months == 1 else gettext('months')}")
    if weeks > 0:
        parts.append(f"{weeks} {gettext('week') if weeks == 1 else gettext('weeks')}")
    if days > 0:
        parts.append(f"{days} {gettext('day') if days == 1 else gettext('days')}")
    if hours > 0:
        parts.append(f"{hours} {gettext('hour') if hours == 1 else gettext('hours')}")
    if minutes > 0:
        parts.append(f"{minutes} {gettext('minute') if minutes == 1 else gettext('minutes')}")
    if secs > 0 or not parts:
        parts.append(f"{secs} {gettext('second') if secs == 1 else gettext('seconds')}")

    return ", ".join(parts)

@app.template_filter('fetcher_status_icons')
def _jinja2_filter_fetcher_status_icons(fetcher_name):
    """Get status icon HTML for a given fetcher.

    This filter checks both built-in fetchers and plugin fetchers for status icons.

    Args:
        fetcher_name: The fetcher name (e.g., 'html_webdriver', 'html_js_zyte')

    Returns:
        str: HTML string containing status icon elements
    """
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import collect_fetcher_status_icons
    from markupsafe import Markup
    from flask import url_for

    icon_data = None

    # First check if it's a plugin fetcher (plugins have priority)
    plugin_icon_data = collect_fetcher_status_icons(fetcher_name)
    if plugin_icon_data:
        icon_data = plugin_icon_data
    # Check if it's a built-in fetcher
    elif hasattr(content_fetchers, fetcher_name):
        fetcher_class = getattr(content_fetchers, fetcher_name)
        if hasattr(fetcher_class, 'get_status_icon_data'):
            icon_data = fetcher_class.get_status_icon_data()

    # Build HTML from icon data
    if icon_data and isinstance(icon_data, dict):
        # Use 'group' from icon_data if specified, otherwise default to 'images'
        group = icon_data.get('group', 'images')

        # Try to use url_for, but fall back to manual URL building if endpoint not registered yet
        try:
            icon_url = url_for('static_content', group=group, filename=icon_data['filename'])
        except:
            # Fallback: build URL manually respecting APPLICATION_ROOT
            from flask import request
            app_root = request.script_root if hasattr(request, 'script_root') else ''
            icon_url = f"{app_root}/static/{group}/{icon_data['filename']}"

        style_attr = f' style="{icon_data["style"]}"' if icon_data.get('style') else ''
        html = f'<img class="status-icon" src="{icon_url}" alt="{icon_data["alt"]}" title="{icon_data["title"]}"{style_attr}>'
        return Markup(html)

    return ''

@app.template_filter('sanitize_tag_class')
def _jinja2_filter_sanitize_tag_class(tag_title):
    """Sanitize a tag title to create a valid CSS class name.
    Removes all non-alphanumeric characters and converts to lowercase.

    Args:
        tag_title: The tag title string

    Returns:
        str: A sanitized string suitable for use as a CSS class name
    """
    import re
    # Remove all non-alphanumeric characters and convert to lowercase
    sanitized = re.sub(r'[^a-zA-Z0-9]', '', tag_title).lower()
    # Ensure it starts with a letter (CSS requirement)
    if sanitized and not sanitized[0].isalpha():
        sanitized = 'tag' + sanitized
    return sanitized if sanitized else 'tag'

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

    # Set datastore reference in notification queue for all_muted checking
    notification_q.set_datastore(datastore)

    # Import and create a wrapper for is_safe_url that has access to app
    from changedetectionio.is_safe_url import is_safe_url as _is_safe_url

    def is_safe_url(target):
        """Wrapper for is_safe_url that passes the app instance"""
        return _is_safe_url(target, app)

    # so far just for read-only via tests, but this will be moved eventually to be the main source
    # (instead of the global var)
    app.config['DATASTORE'] = datastore_o

    # Store batch mode flag to skip background threads when running in batch mode
    app.config['batch_mode'] = config.get('batch_mode', False) if config else False

    # Store the signal in the app config to ensure it's accessible everywhere
    app.config['watch_check_update_SIGNAL'] = watch_check_update

    login_manager = flask_login.LoginManager(app)
    login_manager.login_view = 'login'
    app.secret_key = init_app_secret(config['datastore_path'])

    # Initialize Flask-Babel for i18n support
    available_languages = get_available_languages()
    language_codes = get_language_codes()

    def get_locale():
        # Locale aliases: map browser language codes to translation directory names
        # This handles cases where browsers send standard codes (e.g., zh-TW)
        # but our translations use more specific codes (e.g., zh_Hant_TW)
        locale_aliases = {
            'zh-TW': 'zh_Hant_TW',  # Traditional Chinese: browser sends zh-TW, we use zh_Hant_TW
            'zh_TW': 'zh_Hant_TW',  # Also handle underscore variant
        }

        # 1. Try to get locale from session (user explicitly selected)
        if 'locale' in session:
            return session['locale']

        # 2. Fall back to Accept-Language header
        # Get the best match from browser's Accept-Language header
        browser_locale = request.accept_languages.best_match(language_codes + list(locale_aliases.keys()))

        # 3. Check if we need to map the browser locale to our internal locale
        if browser_locale in locale_aliases:
            return locale_aliases[browser_locale]

        return browser_locale

    # Initialize Babel with locale selector
    babel = Babel(app, locale_selector=get_locale)

    # Make i18n functions available to templates
    app.jinja_env.globals.update(
        _=gettext,
        get_locale=get_locale,
        get_flag_for_locale=get_flag_for_locale,
        available_languages=available_languages
    )

    # Set up a request hook to check authentication for all routes
    @app.before_request
    def check_authentication():
        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)

        if has_password_enabled and not flask_login.current_user.is_authenticated:
            # Permitted
            if request.endpoint and request.endpoint == 'static_content' and request.view_args:
                # Handled by static_content handler
                return None
            # Permitted - static flag icons need to load on login page
            elif request.endpoint and request.endpoint == 'static_flags':
                return None
            # Permitted - language selection should work on login page
            elif request.endpoint and request.endpoint == 'set_language':
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


    watch_api.add_resource(WatchHistoryDiff,
                           '/api/v1/watch/<string:uuid>/difference/<string:from_timestamp>/<string:to_timestamp>',
                           resource_class_kwargs={'datastore': datastore})
    watch_api.add_resource(WatchSingleHistory,
                           '/api/v1/watch/<string:uuid>/history/<string:timestamp>',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})
    watch_api.add_resource(WatchFavicon,
                           '/api/v1/watch/<string:uuid>/favicon',
                           resource_class_kwargs={'datastore': datastore})
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
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})
                           
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
        # Pass the current request path so users are redirected back after login
        return redirect(url_for('login', redirect=request.path))

    @app.route('/logout')
    def logout():
        flask_login.logout_user()

        # Check if there's a redirect parameter to return to after re-login
        redirect_url = request.args.get('redirect')

        # If redirect is provided and safe, pass it to login page
        if redirect_url and is_safe_url(redirect_url):
            return redirect(url_for('login', redirect=redirect_url))

        # Otherwise just go to watchlist
        return redirect(url_for('watchlist.index'))

    @app.route('/set-language/<locale>')
    def set_language(locale):
        """Set the user's preferred language in the session"""
        if not request.cookies:
            logger.error("Cannot set language without session cookie")
            flash("Cannot set language without session cookie", 'error')
            return redirect(url_for('watchlist.index'))

        # Validate the locale against available languages
        if locale in language_codes:
            # Make session permanent so language preference persists across browser sessions
            # NOTE: This is the Flask session cookie (separate from Flask-Login's remember-me auth cookie)
            session.permanent = True
            session['locale'] = locale

            # CRITICAL: Flask-Babel caches the locale in the request context (ctx.babel_locale)
            # We must refresh to clear this cache so the new locale takes effect immediately
            # This is especially important for tests where multiple requests happen rapidly
            from flask_babel import refresh
            refresh()
        else:
            logger.error(f"Invalid locale {locale}, available: {language_codes}")

        # Check if there's a redirect parameter to return to the same page
        redirect_url = request.args.get('redirect')

        # If redirect is provided and safe, use it
        if redirect_url and is_safe_url(redirect_url):
            return redirect(redirect_url)

        # Otherwise redirect to watchlist
        return redirect(url_for('watchlist.index'))

    # https://github.com/pallets/flask/blob/93dd1709d05a1cf0e886df6223377bdab3b077fb/examples/tutorial/flaskr/__init__.py#L39
    # You can divide up the stuff like this
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        # Extract and validate the redirect parameter
        redirect_url = request.args.get('redirect') or request.form.get('redirect')

        # Validate the redirect URL - default to watchlist if invalid
        if redirect_url and is_safe_url(redirect_url):
            validated_redirect = redirect_url
        else:
            validated_redirect = url_for('watchlist.index')

        if request.method == 'GET':
            if flask_login.current_user.is_authenticated:
                # Already logged in - redirect immediately to the target
                flash(gettext("Already logged in"))
                return redirect(validated_redirect)
            flash(gettext("You must be logged in, please log in."), 'error')
            output = render_template("login.html", redirect_url=validated_redirect)
            return output

        user = User()
        user.id = "defaultuser@changedetection.io"

        password = request.form.get('password')

        if (user.check_password(password)):
            flask_login.login_user(user, remember=True)
            # Redirect to the validated URL after successful login
            return redirect(validated_redirect)

        else:
            flash(gettext('Incorrect password'), 'error')

        return redirect(url_for('login', redirect=redirect_url if redirect_url else None))

    @app.before_request
    def before_request_handle_cookie_x_settings():
        # Set the auth cookie path if we're running as X-settings/X-Forwarded-Prefix
        if os.getenv('USE_X_SETTINGS') and 'X-Forwarded-Prefix' in request.headers:
            app.config['REMEMBER_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']
            app.config['SESSION_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']
        return None

    @app.route("/static/flags/<path:flag_path>", methods=['GET'])
    def static_flags(flag_path):
        """Handle flag icon files with subdirectories"""
        from flask import make_response
        import re

        # flag_path comes in as "1x1/de.svg" or "4x3/de.svg"
        if re.match(r'^(1x1|4x3)/[a-z0-9-]+\.svg$', flag_path.lower()):
            # Reconstruct the path safely with additional validation
            parts = flag_path.lower().split('/')
            if len(parts) != 2:
                abort(404)

            subdir = parts[0]
            svg_file = parts[1]

            # Extra validation: ensure subdir is exactly 1x1 or 4x3
            if subdir not in ['1x1', '4x3']:
                abort(404)

            # Extra validation: ensure svg_file only contains safe characters
            if not re.match(r'^[a-z0-9-]+\.svg$', svg_file):
                abort(404)

            try:
                response = make_response(send_from_directory(f"static/flags/{subdir}", svg_file))
                response.headers['Content-type'] = 'image/svg+xml'
                response.headers['Cache-Control'] = 'max-age=86400, public'  # Cache for 24 hours
                return response
            except FileNotFoundError:
                abort(404)
        else:
            abort(404)

    @app.route("/static/<string:group>/<string:filename>", methods=['GET'])
    def static_content(group, filename):
        from flask import make_response
        import re

        # Strict sanitization: only allow a-z, 0-9, and underscore (blocks .. and other traversal)
        group = re.sub(r'[^a-z0-9_-]+', '', group.lower())
        filename = filename

        # Additional safety: reject if sanitization resulted in empty strings
        if not group or not filename:
            abort(404)

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

        if group == 'favicon':
            # Could be sensitive, follow password requirements
            if datastore.data['settings']['application']['password'] and not flask_login.current_user.is_authenticated:
                abort(403)
            # Get the watch object
            watch = datastore.data['watching'].get(filename)
            if not watch:
                abort(404)

            favicon_filename = watch.get_favicon_filename()
            if favicon_filename:
                # Use cached MIME type detection
                filepath = os.path.join(watch.data_dir, favicon_filename)
                mime = get_favicon_mime_type(filepath)

                response = make_response(send_from_directory(watch.data_dir, favicon_filename))
                response.headers['Content-type'] = mime
                response.headers['Cache-Control'] = 'max-age=300, must-revalidate'  # Cache for 5 minutes, then revalidate
                return response

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

        # Handle plugin group specially
        if group == 'plugin':
            # Serve files from plugin static directories
            from changedetectionio.pluggy_interface import plugin_manager
            import os as os_check

            for plugin_name, plugin_obj in plugin_manager.list_name_plugin():
                if hasattr(plugin_obj, 'plugin_static_path'):
                    try:
                        static_path = plugin_obj.plugin_static_path()
                        if static_path and os_check.path.isdir(static_path):
                            # Check if file exists in plugin's static directory
                            plugin_file_path = os_check.path.join(static_path, filename)
                            if os_check.path.isfile(plugin_file_path):
                                # Found the file in a plugin
                                response = make_response(send_from_directory(static_path, filename))
                                response.headers['Cache-Control'] = 'max-age=3600, public'  # Cache for 1 hour
                                return response
                    except Exception as e:
                        logger.debug(f"Error checking plugin {plugin_name} for static file: {e}")
                        pass

            # File not found in any plugin
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
    app.register_blueprint(ui.construct_blueprint(datastore, update_q, worker_pool, queuedWatchMetaData, watch_check_update, llm_summary_q=llm_summary_q))

    import changedetectionio.blueprint.watchlist as watchlist
    app.register_blueprint(watchlist.construct_blueprint(datastore=datastore, update_q=update_q, queuedWatchMetaData=queuedWatchMetaData), url_prefix='')

    # Initialize Socket.IO server conditionally based on settings
    socket_io_enabled = datastore.data['settings']['application'].get('ui', {}).get('socket_io_enabled', True)
    if socket_io_enabled and app.config.get('batch_mode'):
        socket_io_enabled = False
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
        status = worker_pool.get_worker_status()
        
        # Perform health check
        health_result = worker_pool.check_worker_health(
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
    worker_pool.start_workers(n_workers, update_q, notification_q, app, datastore)

    # Skip background threads in batch mode (just process queue and exit)
    batch_mode = app.config.get('batch_mode', False)
    if not batch_mode:
        # @todo handle ctrl break
        ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks, daemon=True, name="TickerThread-ScheduleChecker").start()

        # Start configurable number of notification workers (default 1)
        notification_workers = int(os.getenv("NOTIFICATION_WORKERS", "1"))
        for i in range(notification_workers):
            threading.Thread(
                target=notification_runner,
                args=(i,),
                daemon=True,
                name=f"NotificationRunner-{i}"
            ).start()
        logger.info(f"Started {notification_workers} notification worker(s)")

        llm.start_workers(app=app, datastore=datastore, llm_q=llm_summary_q,
                          n_workers=int(os.getenv("LLM_WORKERS", "1")))

        # Register the LLM queue plugin so changes trigger summary jobs
        from changedetectionio.llm.plugin import LLMQueuePlugin
        from changedetectionio.pluggy_interface import plugin_manager
        plugin_manager.register(LLMQueuePlugin(llm_summary_q), 'llm_queue_plugin')

        # Re-run template path configuration now that all plugins (including LLM) are registered
        _configure_plugin_templates()

        in_pytest = "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ
        # Check for new release version, but not when running in test/build or pytest
        if not os.getenv("GITHUB_REF", False) and not strtobool(os.getenv('DISABLE_VERSION_CHECK', 'no')) and not in_pytest:
            threading.Thread(target=check_for_new_version, daemon=True, name="VersionChecker").start()
    else:
        logger.info("Batch mode: Skipping ticker thread, notification runner, and version checker")

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


def notification_runner(worker_id=0):
    global notification_debug_log
    from datetime import datetime
    import json
    with app.app_context():
        while not app.config.exit.is_set():
            try:
                # Multiple workers can run concurrently (configurable via NOTIFICATION_WORKERS)
                n_object = notification_q.get(block=False)
            except queue.Empty:
                app.config.exit.wait(1)

            else:

                # ── LLM deferred-send gate ─────────────────────────────────────────
                # If the notification was re-queued to wait for LLM data, honour the
                # scheduled retry time before doing any further processing.
                _llm_next_retry = n_object.get('_llm_next_retry_at', 0)
                if _llm_next_retry and _llm_next_retry > time.time():
                    notification_q.put(n_object)
                    app.config.exit.wait(min(_llm_next_retry - time.time(), 2))
                    continue

                # Apply system-config fallbacks first so we can scan the final body/title.
                if not n_object.get('notification_body') and datastore.data['settings']['application'].get('notification_body'):
                    n_object['notification_body'] = datastore.data['settings']['application'].get('notification_body')
                if not n_object.get('notification_title') and datastore.data['settings']['application'].get('notification_title'):
                    n_object['notification_title'] = datastore.data['settings']['application'].get('notification_title')

                # If the body or title references llm_* tokens, wait until LLM data is ready.
                import re as _re
                _llm_scan = (n_object.get('notification_body') or '') + ' ' + (n_object.get('notification_title') or '')
                if _re.search(r'\bllm_(?:summary|headline|importance|sentiment|one_liner)\b', _llm_scan):
                    from changedetectionio.llm.tokens import (
                        is_llm_data_ready, read_llm_tokens,
                        LLM_NOTIFICATION_RETRY_DELAY_SECONDS, LLM_NOTIFICATION_MAX_WAIT_ATTEMPTS,
                    )
                    _llm_uuid     = n_object.get('uuid')
                    _llm_watch    = datastore.data['watching'].get(_llm_uuid) if _llm_uuid else None
                    _llm_snap_id  = n_object.get('_llm_snapshot_id')

                    if _llm_watch and _llm_snap_id and not is_llm_data_ready(_llm_watch.data_dir, _llm_snap_id):
                        _llm_attempts = n_object.get('_llm_wait_attempts', 0)
                        if _llm_attempts < LLM_NOTIFICATION_MAX_WAIT_ATTEMPTS:
                            n_object['_llm_wait_attempts'] = _llm_attempts + 1
                            n_object['_llm_next_retry_at'] = time.time() + LLM_NOTIFICATION_RETRY_DELAY_SECONDS
                            notification_q.put(n_object)
                            logger.debug(
                                f"Notification gate: LLM data pending for {_llm_uuid} "
                                f"(attempt {n_object['_llm_wait_attempts']}/{LLM_NOTIFICATION_MAX_WAIT_ATTEMPTS})"
                            )
                            continue
                        else:
                            logger.warning(
                                f"Notification: LLM data never arrived for {_llm_uuid} after "
                                f"{LLM_NOTIFICATION_MAX_WAIT_ATTEMPTS} attempts — sending without LLM tokens"
                            )
                    elif _llm_watch and _llm_snap_id:
                        # Data is ready — populate the LLM tokens into n_object
                        _llm_data = read_llm_tokens(_llm_watch.data_dir, _llm_snap_id)
                        n_object['llm_summary']    = _llm_data.get('summary', '')
                        n_object['llm_headline']   = _llm_data.get('headline', '')
                        n_object['llm_importance'] = _llm_data.get('importance')
                        n_object['llm_sentiment']  = _llm_data.get('sentiment', '')
                        n_object['llm_one_liner']  = _llm_data.get('one_liner', '')
                # ── end LLM gate ───────────────────────────────────────────────────

                now = datetime.now()
                sent_obj = None

                try:
                    from changedetectionio.notification.handler import process_notification

                    if not n_object.get('notification_format') and datastore.data['settings']['application'].get('notification_format'):
                        n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')
                    if n_object.get('notification_urls', {}):
                        sent_obj = process_notification(n_object, datastore)

                except Exception as e:
                    logger.error(f"Notification worker {worker_id} - Watch URL: {n_object['watch_url']}  Error {str(e)}")

                    # UUID wont be present when we submit a 'test' from the global settings
                    if 'uuid' in n_object:
                        datastore.update_watch(uuid=n_object['uuid'],
                                               update_obj={'last_notification_error': "Notification error detected, goto notification log."})

                    log_lines = str(e).splitlines()
                    notification_debug_log += log_lines

                    with app.app_context():
                        app.config['watch_check_update_SIGNAL'].send(app_context=app, watch_uuid=n_object.get('uuid'))

                # Process notifications
                notification_debug_log+= ["{} - SENDING - {}".format(now.strftime("%c"), json.dumps(sent_obj))]
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
    WAIT_TIME_BETWEEN_LOOP = 1.0 if not IN_PYTEST else 0.01
    if IN_PYTEST:
        # The time between loops should be less than the first .sleep/wait in def wait_for_all_checks() of tests/util.py
        logger.warning(f"Looks like we're in PYTEST! Setting time between searching for items to add to the queue to {WAIT_TIME_BETWEEN_LOOP}s")

    while not app.config.exit.is_set():

        # Periodic worker health check (every 60 seconds)
        now = time.time()
        if now - last_health_check > 60:
            expected_workers = int(os.getenv("FETCH_WORKERS", datastore.data['settings']['requests']['workers']))
            health_result = worker_pool.check_worker_health(
                expected_count=expected_workers,
                update_q=update_q,
                notification_q=notification_q,
                app=app,
                datastore=datastore
            )
            
            if health_result['status'] != 'healthy':
                logger.warning(f"Worker health check: {health_result['message']}")

            last_health_check = now

        # Check if all checks are paused
        if datastore.data['settings']['application'].get('all_paused', False):
            app.config.exit.wait(1)
            continue

        # Get a list of watches by UUID that are currently fetching data
        running_uuids = worker_pool.get_running_uuids()

        # Build set of queued UUIDs once for O(1) lookup instead of O(n) per watch
        queued_uuids = {q_item.item['uuid'] for q_item in update_q.queue}

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

        recheck_time_system_seconds = int(datastore.threshold_seconds)

        # Check for watches outside of the time threshold to put in the thread queue.
        for watch_index, uuid in enumerate(watch_uuid_list):
            # Re #438 - Check queue size every 100 watches for CPU efficiency (not every watch)
            if watch_index % 100 == 0:
                current_queue_size = update_q.qsize()
                if current_queue_size >= MAX_QUEUE_SIZE:
                    logger.debug(f"Queue size limit reached ({current_queue_size}/{MAX_QUEUE_SIZE}), stopping scheduler this iteration.")
                    break

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
            scheduler_source = None
            if watch.get('time_between_check_use_default'):
                time_schedule_limit = datastore.data['settings']['requests'].get('time_schedule_limit', {})
                scheduler_source = 'system/global settings'

            else:
                time_schedule_limit = watch.get('time_schedule_limit')
                scheduler_source = 'watch'

            tz_name = datastore.data['settings']['application'].get('scheduler_timezone_default', os.getenv('TZ', 'UTC').strip())

            if time_schedule_limit and time_schedule_limit.get('enabled'):
                logger.trace(f"{uuid} Time scheduler - Using scheduler settings from {scheduler_source}")
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
                if not uuid in running_uuids and uuid not in queued_uuids:

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

                    # Into the queue with you
                    queued_successfully = worker_pool.queue_item_async_safe(update_q,
                                                                               queuedWatchMetaData.PrioritizedItem(priority=priority,
                                                                                                                   item={'uuid': uuid})
                                                                               )
                    if queued_successfully:
                        logger.debug(
                            f"> Queued watch UUID {uuid} "
                            f"last checked at {watch['last_checked']} "
                            f"queued at {now:0.2f} priority {priority} "
                            f"jitter {watch.jitter_seconds:0.2f}s, "
                            f"{now - watch['last_checked']:0.2f}s since last checked")
                    else:
                        logger.critical(f"CRITICAL: Failed to queue watch UUID {uuid} in ticker thread!")
                        
                    # Reset for next time
                    watch.jitter_seconds = 0

        # Should be low so we can break this out in testing
        app.config.exit.wait(WAIT_TIME_BETWEEN_LOOP)
