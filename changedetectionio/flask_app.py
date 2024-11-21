#!/usr/bin/env python3

import datetime

import flask_login
import locale
import os
import pytz
import queue
import threading
import time
import timeago

from .processors import find_processors, get_parent_module, get_custom_watch_obj_for_processor
from .safe_jinja import render as jinja_render
from changedetectionio.strtobool import strtobool
from copy import deepcopy
from functools import wraps
from threading import Event

from feedgen.feed import FeedGenerator
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
from flask_paginate import Pagination, get_page_parameter
from flask_restful import abort, Api
from flask_cors import CORS
from flask_wtf import CSRFProtect
from loguru import logger
from zoneinfo import ZoneInfo


from changedetectionio import html_tools, __version__
from changedetectionio import queuedWatchMetaData
from changedetectionio.api import api_v1

datastore = None

# Local
running_update_threads = []
ticker_thread = None

extra_stylesheets = []

update_q = queue.PriorityQueue()
notification_q = queue.Queue()
MAX_QUEUE_SIZE = 2000

app = Flask(__name__,
            static_url_path="",
            static_folder="static",
            template_folder="templates")

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

@app.template_filter('format_number_locale')
def _jinja2_filter_format_number_locale(value: float) -> str:
    "Formats for example 4000.10 to the local locale default of 4,000.10"
    # Format the number with two decimal places (locale format string will return 6 decimal)
    formatted_value = locale.format_string("%.2f", value, grouping=True)

    return formatted_value

# We use the whole watch object from the store/JSON so we can see if there's some related status in terms of a thread
# running or something similar.
@app.template_filter('format_last_checked_time')
def _jinja2_filter_datetime(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    # Worker thread tells us which UUID it is currently processing.
    for t in running_update_threads:
        if t.current_uuid == watch_obj['uuid']:
            return '<span class="spinner"></span><span> Checking now</span>'

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

def login_optionally_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):

        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)

        # Permitted
        if request.endpoint == 'static_content' and request.view_args['group'] == 'styles':
            return func(*args, **kwargs)
        # Permitted
        elif request.endpoint == 'diff_history_page' and datastore.data['settings']['application'].get('shared_diff_access'):
            return func(*args, **kwargs)
        elif request.method in flask_login.config.EXEMPT_METHODS:
            return func(*args, **kwargs)
        elif app.config.get('LOGIN_DISABLED'):
            return func(*args, **kwargs)
        elif has_password_enabled and not current_user.is_authenticated:
            return app.login_manager.unauthorized()

        return func(*args, **kwargs)

    return decorated_view

def changedetection_app(config=None, datastore_o=None):
    logger.trace("TRACE log is enabled")

    global datastore
    datastore = datastore_o

    # so far just for read-only via tests, but this will be moved eventually to be the main source
    # (instead of the global var)
    app.config['DATASTORE'] = datastore_o

    login_manager = flask_login.LoginManager(app)
    login_manager.login_view = 'login'
    app.secret_key = init_app_secret(config['datastore_path'])


    watch_api.add_resource(api_v1.WatchSingleHistory,
                           '/api/v1/watch/<string:uuid>/history/<string:timestamp>',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(api_v1.WatchHistory,
                           '/api/v1/watch/<string:uuid>/history',
                           resource_class_kwargs={'datastore': datastore})

    watch_api.add_resource(api_v1.CreateWatch, '/api/v1/watch',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(api_v1.Watch, '/api/v1/watch/<string:uuid>',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(api_v1.SystemInfo, '/api/v1/systeminfo',
                           resource_class_kwargs={'datastore': datastore, 'update_q': update_q})

    watch_api.add_resource(api_v1.Import,
                           '/api/v1/import',
                           resource_class_kwargs={'datastore': datastore})

    # Setup cors headers to allow all domains
    # https://flask-cors.readthedocs.io/en/latest/
    #    CORS(app)



    @login_manager.user_loader
    def user_loader(email):
        user = User()
        user.get_user(email)
        return user

    @login_manager.unauthorized_handler
    def unauthorized_handler():
        flash("You must be logged in, please log in.", 'error')
        return redirect(url_for('login', next=url_for('index')))

    @app.route('/logout')
    def logout():
        flask_login.logout_user()
        return redirect(url_for('index'))

    # https://github.com/pallets/flask/blob/93dd1709d05a1cf0e886df6223377bdab3b077fb/examples/tutorial/flaskr/__init__.py#L39
    # You can divide up the stuff like this
    @app.route('/login', methods=['GET', 'POST'])
    def login():

        if request.method == 'GET':
            if flask_login.current_user.is_authenticated:
                flash("Already logged in")
                return redirect(url_for("index"))

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
            # return redirect(next or url_for('index'))
            # We would sometimes get login loop errors on sites hosted in sub-paths

            # note for the future:
            #            if not is_safe_url(next):
            #                return flask.abort(400)
            return redirect(url_for('index'))

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

    @app.route("/rss", methods=['GET'])
    def rss():
        now = time.time()
        # Always requires token set
        app_rss_token = datastore.data['settings']['application'].get('rss_access_token')
        rss_url_token = request.args.get('token')
        if rss_url_token != app_rss_token:
            return "Access denied, bad token", 403

        from . import diff
        limit_tag = request.args.get('tag', '').lower().strip()
        # Be sure limit_tag is a uuid
        for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
            if limit_tag == tag.get('title', '').lower().strip():
                limit_tag = uuid

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []

        # @todo needs a .itemsWithTag() or something - then we can use that in Jinaj2 and throw this away
        for uuid, watch in datastore.data['watching'].items():
            # @todo tag notification_muted skip also (improve Watch model)
            if datastore.data['settings']['application'].get('rss_hide_muted_watches') and watch.get('notification_muted'):
                continue
            if limit_tag and not limit_tag in watch['tags']:
                continue
            watch['uuid'] = uuid
            sorted_watches.append(watch)

        sorted_watches.sort(key=lambda x: x.last_changed, reverse=False)

        fg = FeedGenerator()
        fg.title('changedetection.io')
        fg.description('Feed description')
        fg.link(href='https://changedetection.io')

        for watch in sorted_watches:

            dates = list(watch.history.keys())
            # Re #521 - Don't bother processing this one if theres less than 2 snapshots, means we never had a change detected.
            if len(dates) < 2:
                continue

            if not watch.viewed:
                # Re #239 - GUID needs to be individual for each event
                # @todo In the future make this a configurable link back (see work on BASE_URL https://github.com/dgtlmoon/changedetection.io/pull/228)
                guid = "{}/{}".format(watch['uuid'], watch.last_changed)
                fe = fg.add_entry()

                # Include a link to the diff page, they will have to login here to see if password protection is enabled.
                # Description is the page you watch, link takes you to the diff JS UI page
                # Dict val base_url will get overriden with the env var if it is set.
                ext_base_url = datastore.data['settings']['application'].get('active_base_url')

                # Because we are called via whatever web server, flask should figure out the right path (
                diff_link = {'href': url_for('diff_history_page', uuid=watch['uuid'], _external=True)}

                fe.link(link=diff_link)

                # @todo watch should be a getter - watch.get('title') (internally if URL else..)

                watch_title = watch.get('title') if watch.get('title') else watch.get('url')
                fe.title(title=watch_title)

                html_diff = diff.render_diff(previous_version_file_contents=watch.get_history_snapshot(dates[-2]),
                                             newest_version_file_contents=watch.get_history_snapshot(dates[-1]),
                                             include_equal=False,
                                             line_feed_sep="<br>")

                # @todo Make this configurable and also consider html-colored markup
                # @todo User could decide if <link> goes to the diff page, or to the watch link
                rss_template = "<html><body>\n<h4><a href=\"{{watch_url}}\">{{watch_title}}</a></h4>\n<p>{{html_diff}}</p>\n</body></html>\n"
                content = jinja_render(template_str=rss_template, watch_title=watch_title, html_diff=html_diff, watch_url=watch.link)

                fe.content(content=content, type='CDATA')

                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        logger.trace(f"RSS generated in {time.time() - now:.3f}s")
        return response

    @app.route("/", methods=['GET'])
    @login_optionally_required
    def index():
        global datastore
        from changedetectionio import forms

        active_tag_req = request.args.get('tag', '').lower().strip()
        active_tag_uuid = active_tag = None

        # Be sure limit_tag is a uuid
        if active_tag_req:
            for uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
                if active_tag_req == tag.get('title', '').lower().strip() or active_tag_req == uuid:
                    active_tag = tag
                    active_tag_uuid = uuid
                    break


        # Redirect for the old rss path which used the /?rss=true
        if request.args.get('rss'):
            return redirect(url_for('rss', tag=active_tag_uuid))

        op = request.args.get('op')
        if op:
            uuid = request.args.get('uuid')
            if op == 'pause':
                datastore.data['watching'][uuid].toggle_pause()
            elif op == 'mute':
                datastore.data['watching'][uuid].toggle_mute()

            datastore.needs_write = True
            return redirect(url_for('index', tag = active_tag_uuid))

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []
        with_errors = request.args.get('with_errors') == "1"
        errored_count = 0
        search_q = request.args.get('q').strip().lower() if request.args.get('q') else False
        for uuid, watch in datastore.data['watching'].items():
            if with_errors and not watch.get('last_error'):
                continue

            if active_tag_uuid and not active_tag_uuid in watch['tags']:
                    continue
            if watch.get('last_error'):
                errored_count += 1

            if search_q:
                if (watch.get('title') and search_q in watch.get('title').lower()) or search_q in watch.get('url', '').lower():
                    sorted_watches.append(watch)
                elif watch.get('last_error') and search_q in watch.get('last_error').lower():
                    sorted_watches.append(watch)
            else:
                sorted_watches.append(watch)

        form = forms.quickWatchForm(request.form)
        page = request.args.get(get_page_parameter(), type=int, default=1)
        total_count = len(sorted_watches)

        pagination = Pagination(page=page,
                                total=total_count,
                                per_page=datastore.data['settings']['application'].get('pager_size', 50), css_framework="semantic")

        sorted_tags = sorted(datastore.data['settings']['application'].get('tags').items(), key=lambda x: x[1]['title'])
        output = render_template(
            "watch-overview.html",
                                 # Don't link to hosting when we're on the hosting environment
                                 active_tag=active_tag,
                                 active_tag_uuid=active_tag_uuid,
                                 app_rss_token=datastore.data['settings']['application'].get('rss_access_token'),
                                 datastore=datastore,
                                 errored_count=errored_count,
                                 form=form,
                                 guid=datastore.data['app_guid'],
                                 has_proxies=datastore.proxy_list,
                                 has_unviewed=datastore.has_unviewed,
                                 hosted_sticky=os.getenv("SALTED_PASS", False) == False,
                                 pagination=pagination,
                                 queued_uuids=[q_uuid.item['uuid'] for q_uuid in update_q.queue],
                                 search_q=request.args.get('q','').strip(),
                                 sort_attribute=request.args.get('sort') if request.args.get('sort') else request.cookies.get('sort'),
                                 sort_order=request.args.get('order') if request.args.get('order') else request.cookies.get('order'),
                                 system_default_fetcher=datastore.data['settings']['application'].get('fetch_backend'),
                                 tags=sorted_tags,
                                 watches=sorted_watches
                                 )

        if session.get('share-link'):
            del(session['share-link'])

        resp = make_response(output)

        # The template can run on cookie or url query info
        if request.args.get('sort'):
            resp.set_cookie('sort', request.args.get('sort'))
        if request.args.get('order'):
            resp.set_cookie('order', request.args.get('order'))

        return resp



    # AJAX endpoint for sending a test
    @app.route("/notification/send-test/<string:watch_uuid>", methods=['POST'])
    @app.route("/notification/send-test", methods=['POST'])
    @app.route("/notification/send-test/", methods=['POST'])
    @login_optionally_required
    def ajax_callback_send_notification_test(watch_uuid=None):

        # Watch_uuid could be unset in the case it`s used in tag editor, global settings
        import apprise
        import random
        from .apprise_asset import asset
        apobj = apprise.Apprise(asset=asset)

        # so that the custom endpoints are registered
        from changedetectionio.apprise_plugin import apprise_custom_api_call_wrapper
        is_global_settings_form = request.args.get('mode', '') == 'global-settings'
        is_group_settings_form = request.args.get('mode', '') == 'group-settings'

        # Use an existing random one on the global/main settings form
        if not watch_uuid and (is_global_settings_form or is_group_settings_form) \
                and datastore.data.get('watching'):
            logger.debug(f"Send test notification - Choosing random Watch {watch_uuid}")
            watch_uuid = random.choice(list(datastore.data['watching'].keys()))

        if not watch_uuid:
            return make_response("Error: You must have atleast one watch configured for 'test notification' to work", 400)

        watch = datastore.data['watching'].get(watch_uuid)

        notification_urls = None

        if request.form.get('notification_urls'):
            notification_urls = request.form['notification_urls'].strip().splitlines()

        if not notification_urls:
            logger.debug("Test notification - Trying by group/tag in the edit form if available")
            # On an edit page, we should also fire off to the tags if they have notifications
            if request.form.get('tags') and request.form['tags'].strip():
                for k in request.form['tags'].split(','):
                    tag = datastore.tag_exists_by_name(k.strip())
                    notification_urls = tag.get('notifications_urls') if tag and tag.get('notifications_urls') else None

        if not notification_urls and not is_global_settings_form and not is_group_settings_form:
            # In the global settings, use only what is typed currently in the text box
            logger.debug("Test notification - Trying by global system settings notifications")
            if datastore.data['settings']['application'].get('notification_urls'):
                notification_urls = datastore.data['settings']['application']['notification_urls']


        if not notification_urls:
            return 'Error: No Notification URLs set/found'

        for n_url in notification_urls:
            if len(n_url.strip()):
                if not apobj.add(n_url):
                    return f'Error:  {n_url} is not a valid AppRise URL.'

        try:
            # use the same as when it is triggered, but then override it with the form test values
            n_object = {
                'watch_url': request.form.get('window_url', "https://changedetection.io"),
                'notification_urls': notification_urls
            }

            # Only use if present, if not set in n_object it should use the default system value
            if 'notification_format' in request.form and request.form['notification_format'].strip():
                n_object['notification_format'] = request.form.get('notification_format', '').strip()

            if 'notification_title' in request.form and request.form['notification_title'].strip():
                n_object['notification_title'] = request.form.get('notification_title', '').strip()

            if 'notification_body' in request.form and request.form['notification_body'].strip():
                n_object['notification_body'] = request.form.get('notification_body', '').strip()

            n_object.update(watch.extra_notification_token_values())

            from . import update_worker
            new_worker = update_worker.update_worker(update_q, notification_q, app, datastore)
            new_worker.queue_notification_for_watch(notification_q=notification_q, n_object=n_object, watch=watch)
        except Exception as e:
            return make_response(f"Error: str(e)", 400)

        return 'OK - Sent test notifications'


    @app.route("/clear_history/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def clear_watch_history(uuid):
        try:
            datastore.clear_watch_history(uuid)
        except KeyError:
            flash('Watch not found', 'error')
        else:
            flash("Cleared snapshot history for watch {}".format(uuid))

        return redirect(url_for('index'))

    @app.route("/clear_history", methods=['GET', 'POST'])
    @login_optionally_required
    def clear_all_history():

        if request.method == 'POST':
            confirmtext = request.form.get('confirmtext')

            if confirmtext == 'clear':
                changes_removed = 0
                for uuid in datastore.data['watching'].keys():
                    datastore.clear_watch_history(uuid)
                    #TODO: KeyError not checked, as it is above

                flash("Cleared snapshot history for all watches")
            else:
                flash('Incorrect confirmation text.', 'error')

            return redirect(url_for('index'))

        output = render_template("clear_all_history.html")
        return output

    def _watch_has_tag_options_set(watch):
        """This should be fixed better so that Tag is some proper Model, a tag is just a Watch also"""
        for tag_uuid, tag in datastore.data['settings']['application'].get('tags', {}).items():
            if tag_uuid in watch.get('tags', []) and (tag.get('include_filters') or tag.get('subtractive_selectors')):
                return True

    @app.route("/edit/<string:uuid>", methods=['GET', 'POST'])
    @login_optionally_required
    # https://stackoverflow.com/questions/42984453/wtforms-populate-form-with-data-if-data-exists
    # https://wtforms.readthedocs.io/en/3.0.x/forms/#wtforms.form.Form.populate_obj ?
    def edit_page(uuid):
        from . import forms
        from .blueprint.browser_steps.browser_steps import browser_step_ui_config
        from . import processors
        import importlib

        # More for testing, possible to return the first/only
        if not datastore.data['watching'].keys():
            flash("No watches to edit", "error")
            return redirect(url_for('index'))

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        if not uuid in datastore.data['watching']:
            flash("No watch with the UUID %s found." % (uuid), "error")
            return redirect(url_for('index'))

        switch_processor = request.args.get('switch_processor')
        if switch_processor:
            for p in processors.available_processors():
                if p[0] == switch_processor:
                    datastore.data['watching'][uuid]['processor'] = switch_processor
                    flash(f"Switched to mode - {p[1]}.")
                    datastore.clear_watch_history(uuid)
                    redirect(url_for('edit_page', uuid=uuid))

        # be sure we update with a copy instead of accidently editing the live object by reference
        default = deepcopy(datastore.data['watching'][uuid])

        # Defaults for proxy choice
        if datastore.proxy_list is not None:  # When enabled
            # @todo
            # Radio needs '' not None, or incase that the chosen one no longer exists
            if default['proxy'] is None or not any(default['proxy'] in tup for tup in datastore.proxy_list):
                default['proxy'] = ''
        # proxy_override set to the json/text list of the items

        # Does it use some custom form? does one exist?
        processor_name = datastore.data['watching'][uuid].get('processor', '')
        processor_classes = next((tpl for tpl in find_processors() if tpl[1] == processor_name), None)
        if not processor_classes:
            flash(f"Cannot load the edit form for processor/plugin '{processor_classes[1]}', plugin missing?", 'error')
            return redirect(url_for('index'))

        parent_module = get_parent_module(processor_classes[0])

        try:
            # Get the parent of the "processor.py" go up one, get the form (kinda spaghetti but its reusing existing code)
            forms_module = importlib.import_module(f"{parent_module.__name__}.forms")
            # Access the 'processor_settings_form' class from the 'forms' module
            form_class = getattr(forms_module, 'processor_settings_form')
        except ModuleNotFoundError as e:
            # .forms didnt exist
            form_class = forms.processor_text_json_diff_form
        except AttributeError as e:
            # .forms exists but no useful form
            form_class = forms.processor_text_json_diff_form

        form = form_class(formdata=request.form if request.method == 'POST' else None,
                          data=default,
                          extra_notification_tokens=default.extra_notification_token_values()
                          )

        # For the form widget tag UUID back to "string name" for the field
        form.tags.datastore = datastore

        # Used by some forms that need to dig deeper
        form.datastore = datastore
        form.watch = default

        for p in datastore.extra_browsers:
            form.fetch_backend.choices.append(p)

        form.fetch_backend.choices.append(("system", 'System settings default'))

        # form.browser_steps[0] can be assumed that we 'goto url' first

        if datastore.proxy_list is None:
            # @todo - Couldn't get setattr() etc dynamic addition working, so remove it instead
            del form.proxy
        else:
            form.proxy.choices = [('', 'Default')]
            for p in datastore.proxy_list:
                form.proxy.choices.append(tuple((p, datastore.proxy_list[p]['label'])))


        if request.method == 'POST' and form.validate():

            # If they changed processor, it makes sense to reset it.
            if datastore.data['watching'][uuid].get('processor') != form.data.get('processor'):
                datastore.data['watching'][uuid].clear_watch()
                flash("Reset watch history due to change of processor")

            extra_update_obj = {
                'consecutive_filter_failures': 0,
                'last_error' : False
            }

            if request.args.get('unpause_on_save'):
                extra_update_obj['paused'] = False

            extra_update_obj['time_between_check'] = form.time_between_check.data

             # Ignore text
            form_ignore_text = form.ignore_text.data
            datastore.data['watching'][uuid]['ignore_text'] = form_ignore_text

            # Be sure proxy value is None
            if datastore.proxy_list is not None and form.data['proxy'] == '':
                extra_update_obj['proxy'] = None

            # Unsetting all filter_text methods should make it go back to default
            # This particularly affects tests running
            if 'filter_text_added' in form.data and not form.data.get('filter_text_added') \
                    and 'filter_text_replaced' in form.data and not form.data.get('filter_text_replaced') \
                    and 'filter_text_removed' in form.data and not form.data.get('filter_text_removed'):
                extra_update_obj['filter_text_added'] = True
                extra_update_obj['filter_text_replaced'] = True
                extra_update_obj['filter_text_removed'] = True

            # Because wtforms doesn't support accessing other data in process_ , but we convert the CSV list of tags back to a list of UUIDs
            tag_uuids = []
            if form.data.get('tags'):
                # Sometimes in testing this can be list, dont know why
                if type(form.data.get('tags')) == list:
                    extra_update_obj['tags'] = form.data.get('tags')
                else:
                    for t in form.data.get('tags').split(','):
                        tag_uuids.append(datastore.add_tag(name=t))
                    extra_update_obj['tags'] = tag_uuids

            datastore.data['watching'][uuid].update(form.data)
            datastore.data['watching'][uuid].update(extra_update_obj)

            if not datastore.data['watching'][uuid].get('tags'):
                # Force it to be a list, because form.data['tags'] will be string if nothing found
                # And del(form.data['tags'] ) wont work either for some reason
                datastore.data['watching'][uuid]['tags'] = []

            # Recast it if need be to right data Watch handler
            watch_class = get_custom_watch_obj_for_processor(form.data.get('processor'))
            datastore.data['watching'][uuid] = watch_class(datastore_path=datastore_o.datastore_path, default=datastore.data['watching'][uuid])
            flash("Updated watch - unpaused!" if request.args.get('unpause_on_save') else "Updated watch.")

            # Re #286 - We wait for syncing new data to disk in another thread every 60 seconds
            # But in the case something is added we should save straight away
            datastore.needs_write_urgent = True

            if not datastore.data['watching'][uuid].get('paused'):
                # Queue the watch for immediate recheck, with a higher priority
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            # Diff page [edit] link should go back to diff page
            if request.args.get("next") and request.args.get("next") == 'diff':
                return redirect(url_for('diff_history_page', uuid=uuid))

            return redirect(url_for('index'))

        else:
            if request.method == 'POST' and not form.validate():
                flash("An error occurred, please see below.", "error")

            visualselector_data_is_ready = datastore.visualselector_data_is_ready(uuid)


            # JQ is difficult to install on windows and must be manually added (outside requirements.txt)
            jq_support = True
            try:
                import jq
            except ModuleNotFoundError:
                jq_support = False

            watch = datastore.data['watching'].get(uuid)

            system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

            is_html_webdriver = False
            if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
                is_html_webdriver = True

            # Only works reliably with Playwright
            visualselector_enabled = os.getenv('PLAYWRIGHT_DRIVER_URL', False) and is_html_webdriver
            template_args = {
                'available_processors': processors.available_processors(),
                'browser_steps_config': browser_step_ui_config,
                'emailprefix': os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                'extra_title': f" - Edit - {watch.label}",
                'extra_processor_config': form.extra_tab_content(),
                'extra_notification_token_placeholder_info': datastore.get_unique_notification_token_placeholders_available(),
                'form': form,
                'has_default_notification_urls': True if len(datastore.data['settings']['application']['notification_urls']) else False,
                'has_extra_headers_file': len(datastore.get_all_headers_in_textfile_for_watch(uuid=uuid)) > 0,
                'has_special_tag_options': _watch_has_tag_options_set(watch=watch),
                'is_html_webdriver': is_html_webdriver,
                'jq_support': jq_support,
                'playwright_enabled': os.getenv('PLAYWRIGHT_DRIVER_URL', False),
                'settings_application': datastore.data['settings']['application'],
                'using_global_webdriver_wait': not default['webdriver_delay'],
                'uuid': uuid,
                'visualselector_enabled': visualselector_enabled,
                'watch': watch
            }

            included_content = None
            if form.extra_form_content():
                # So that the extra panels can access _helpers.html etc, we set the environment to load from templates/
                # And then render the code from the module
                from jinja2 import Environment, FileSystemLoader
                import importlib.resources
                templates_dir = str(importlib.resources.files("changedetectionio").joinpath('templates'))
                env = Environment(loader=FileSystemLoader(templates_dir))
                template = env.from_string(form.extra_form_content())
                included_content = template.render(**template_args)

            output = render_template("edit.html",
                                     extra_tab_content=form.extra_tab_content() if form.extra_tab_content() else None,
                                     extra_form_content=included_content,
                                     **template_args
                                     )

        return output

    @app.route("/settings", methods=['GET', "POST"])
    @login_optionally_required
    def settings_page():
        from changedetectionio import forms
        from datetime import datetime

        default = deepcopy(datastore.data['settings'])
        if datastore.proxy_list is not None:
            available_proxies = list(datastore.proxy_list.keys())
            # When enabled
            system_proxy = datastore.data['settings']['requests']['proxy']
            # In the case it doesnt exist anymore
            if not system_proxy in available_proxies:
                system_proxy = None

            default['requests']['proxy'] = system_proxy if system_proxy is not None else available_proxies[0]
            # Used by the form handler to keep or remove the proxy settings
            default['proxy_list'] = available_proxies[0]


        # Don't use form.data on POST so that it doesnt overrid the checkbox status from the POST status
        form = forms.globalSettingsForm(formdata=request.form if request.method == 'POST' else None,
                                        data=default,
                                        extra_notification_tokens=datastore.get_unique_notification_tokens_available()
                                        )

        # Remove the last option 'System default'
        form.application.form.notification_format.choices.pop()

        if datastore.proxy_list is None:
            # @todo - Couldn't get setattr() etc dynamic addition working, so remove it instead
            del form.requests.form.proxy
        else:
            form.requests.form.proxy.choices = []
            for p in datastore.proxy_list:
                form.requests.form.proxy.choices.append(tuple((p, datastore.proxy_list[p]['label'])))


        if request.method == 'POST':
            # Password unset is a GET, but we can lock the session to a salted env password to always need the password
            if form.application.form.data.get('removepassword_button', False):
                # SALTED_PASS means the password is "locked" to what we set in the Env var
                if not os.getenv("SALTED_PASS", False):
                    datastore.remove_password()
                    flash("Password protection removed.", 'notice')
                    flask_login.logout_user()
                    return redirect(url_for('settings_page'))

            if form.validate():
                # Don't set password to False when a password is set - should be only removed with the `removepassword` button
                app_update = dict(deepcopy(form.data['application']))

                # Never update password with '' or False (Added by wtforms when not in submission)
                if 'password' in app_update and not app_update['password']:
                    del (app_update['password'])

                datastore.data['settings']['application'].update(app_update)
                datastore.data['settings']['requests'].update(form.data['requests'])

                if not os.getenv("SALTED_PASS", False) and len(form.application.form.password.encrypted_password):
                    datastore.data['settings']['application']['password'] = form.application.form.password.encrypted_password
                    datastore.needs_write_urgent = True
                    flash("Password protection enabled.", 'notice')
                    flask_login.logout_user()
                    return redirect(url_for('index'))

                datastore.needs_write_urgent = True
                flash("Settings updated.")

            else:
                flash("An error occurred, please see below.", "error")

        # Convert to ISO 8601 format, all date/time relative events stored as UTC time
        utc_time = datetime.now(ZoneInfo("UTC")).isoformat()

        output = render_template("settings.html",
                                 api_key=datastore.data['settings']['application'].get('api_access_token'),
                                 emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                                 extra_notification_token_placeholder_info=datastore.get_unique_notification_token_placeholders_available(),
                                 form=form,
                                 hide_remove_pass=os.getenv("SALTED_PASS", False),
                                 min_system_recheck_seconds=int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3)),
                                 settings_application=datastore.data['settings']['application'],
                                 utc_time=utc_time,
                                 )

        return output

    @app.route("/settings/reset-api-key", methods=['GET'])
    @login_optionally_required
    def settings_reset_api_key():
        import secrets
        secret = secrets.token_hex(16)
        datastore.data['settings']['application']['api_access_token'] = secret
        datastore.needs_write_urgent = True
        flash("API Key was regenerated.")
        return redirect(url_for('settings_page')+'#api')

    @app.route("/import", methods=['GET', "POST"])
    @login_optionally_required
    def import_page():
        remaining_urls = []
        from . import forms

        if request.method == 'POST':

            from .importer import import_url_list, import_distill_io_json

            # URL List import
            if request.values.get('urls') and len(request.values.get('urls').strip()):
                # Import and push into the queue for immediate update check
                importer = import_url_list()
                importer.run(data=request.values.get('urls'), flash=flash, datastore=datastore, processor=request.values.get('processor', 'text_json_diff'))
                for uuid in importer.new_uuids:
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

                if len(importer.remaining_data) == 0:
                    return redirect(url_for('index'))
                else:
                    remaining_urls = importer.remaining_data

            # Distill.io import
            if request.values.get('distill-io') and len(request.values.get('distill-io').strip()):
                # Import and push into the queue for immediate update check
                d_importer = import_distill_io_json()
                d_importer.run(data=request.values.get('distill-io'), flash=flash, datastore=datastore)
                for uuid in d_importer.new_uuids:
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            # XLSX importer
            if request.files and request.files.get('xlsx_file'):
                file = request.files['xlsx_file']
                from .importer import import_xlsx_wachete, import_xlsx_custom

                if request.values.get('file_mapping') == 'wachete':
                    w_importer = import_xlsx_wachete()
                    w_importer.run(data=file, flash=flash, datastore=datastore)
                else:
                    w_importer = import_xlsx_custom()
                    # Building mapping of col # to col # type
                    map = {}
                    for i in range(10):
                        c = request.values.get(f"custom_xlsx[col_{i}]")
                        v = request.values.get(f"custom_xlsx[col_type_{i}]")
                        if c and v:
                            map[int(c)] = v

                    w_importer.import_profile = map
                    w_importer.run(data=file, flash=flash, datastore=datastore)

                for uuid in w_importer.new_uuids:
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

        # Could be some remaining, or we could be on GET
        form = forms.importForm(formdata=request.form if request.method == 'POST' else None)
        output = render_template("import.html",
                                 form=form,
                                 import_url_list_remaining="\n".join(remaining_urls),
                                 original_distill_json=''
                                 )
        return output

    # Clear all statuses, so we do not see the 'unviewed' class
    @app.route("/form/mark-all-viewed", methods=['GET'])
    @login_optionally_required
    def mark_all_viewed():

        # Save the current newest history as the most recently viewed
        with_errors = request.args.get('with_errors') == "1"
        for watch_uuid, watch in datastore.data['watching'].items():
            if with_errors and not watch.get('last_error'):
                continue
            datastore.set_last_viewed(watch_uuid, int(time.time()))

        return redirect(url_for('index'))

    @app.route("/diff/<string:uuid>", methods=['GET', 'POST'])
    @login_optionally_required
    def diff_history_page(uuid):

        from changedetectionio import forms

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]
        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('index'))

        # For submission of requesting an extract
        extract_form = forms.extractDataForm(request.form)
        if request.method == 'POST':
            if not extract_form.validate():
                flash("An error occurred, please see below.", "error")

            else:
                extract_regex = request.form.get('extract_regex').strip()
                output = watch.extract_regex_from_all_history(extract_regex)
                if output:
                    watch_dir = os.path.join(datastore_o.datastore_path, uuid)
                    response = make_response(send_from_directory(directory=watch_dir, path=output, as_attachment=True))
                    response.headers['Content-type'] = 'text/csv'
                    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                    response.headers['Pragma'] = 'no-cache'
                    response.headers['Expires'] = 0
                    return response


                flash('Nothing matches that RegEx', 'error')
                redirect(url_for('diff_history_page', uuid=uuid)+'#extract')

        history = watch.history
        dates = list(history.keys())

        if len(dates) < 2:
            flash("Not enough saved change detection snapshots to produce a report.", "error")
            return redirect(url_for('index'))

        # Save the current newest history as the most recently viewed
        datastore.set_last_viewed(uuid, time.time())

        # Read as binary and force decode as UTF-8
        # Windows may fail decode in python if we just use 'r' mode (chardet decode exception)
        from_version = request.args.get('from_version')
        from_version_index = -2  # second newest
        if from_version and from_version in dates:
            from_version_index = dates.index(from_version)
        else:
            from_version = dates[from_version_index]

        try:
            from_version_file_contents = watch.get_history_snapshot(dates[from_version_index])
        except Exception as e:
            from_version_file_contents = f"Unable to read to-version at index {dates[from_version_index]}.\n"

        to_version = request.args.get('to_version')
        to_version_index = -1
        if to_version and to_version in dates:
            to_version_index = dates.index(to_version)
        else:
            to_version = dates[to_version_index]

        try:
            to_version_file_contents = watch.get_history_snapshot(dates[to_version_index])
        except Exception as e:
            to_version_file_contents = "Unable to read to-version at index{}.\n".format(dates[to_version_index])

        screenshot_url = watch.get_screenshot()

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True

        password_enabled_and_share_is_off = False
        if datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False):
            password_enabled_and_share_is_off = not datastore.data['settings']['application'].get('shared_diff_access')

        output = render_template("diff.html",
                                 current_diff_url=watch['url'],
                                 from_version=str(from_version),
                                 to_version=str(to_version),
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label}",
                                 extract_form=extract_form,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 last_error_text=watch.get_error_text(),
                                 left_sticky=True,
                                 newest=to_version_file_contents,
                                 newest_version_timestamp=dates[-1],
                                 password_enabled_and_share_is_off=password_enabled_and_share_is_off,
                                 from_version_file_contents=from_version_file_contents,
                                 to_version_file_contents=to_version_file_contents,
                                 screenshot=screenshot_url,
                                 uuid=uuid,
                                 versions=dates, # All except current/last
                                 watch_a=watch
                                 )

        return output

    @app.route("/preview/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def preview_page(uuid):
        content = []
        versions = []
        timestamp = None

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('index'))

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'
        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]

        is_html_webdriver = False
        if (watch.get('fetch_backend') == 'system' and system_uses_webdriver) or watch.get('fetch_backend') == 'html_webdriver' or watch.get('fetch_backend', '').startswith('extra_browser_'):
            is_html_webdriver = True
        triggered_line_numbers = []
        if datastore.data['watching'][uuid].history_n == 0 and (watch.get_error_text() or watch.get_error_snapshot()):
            flash("Preview unavailable - No fetch/check completed or triggers not reached", "error")
        else:
            # So prepare the latest preview or not
            preferred_version = request.args.get('version')
            versions = list(watch.history.keys())
            timestamp = versions[-1]
            if preferred_version and preferred_version in versions:
                timestamp = preferred_version

            try:
                versions = list(watch.history.keys())
                content = watch.get_history_snapshot(timestamp)

                triggered_line_numbers = html_tools.strip_ignore_text(content=content,
                                                                      wordlist=watch['trigger_text'],
                                                                      mode='line numbers'
                                                                      )

            except Exception as e:
                content.append({'line': f"File doesnt exist or unable to read timestamp {timestamp}", 'classes': ''})

        output = render_template("preview.html",
                                 content=content,
                                 current_version=timestamp,
                                 history_n=watch.history_n,
                                 extra_stylesheets=extra_stylesheets,
                                 extra_title=f" - Diff - {watch.label} @ {timestamp}",
                                 triggered_line_numbers=triggered_line_numbers,
                                 current_diff_url=watch['url'],
                                 screenshot=watch.get_screenshot(),
                                 watch=watch,
                                 uuid=uuid,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_text=watch.get_error_text(),
                                 last_error_screenshot=watch.get_error_snapshot(),
                                 versions=versions
                                )


        return output

    @app.route("/settings/notification-logs", methods=['GET'])
    @login_optionally_required
    def notification_logs():
        global notification_debug_log
        output = render_template("notification-log.html",
                                 logs=notification_debug_log if len(notification_debug_log) else ["Notification logs are empty - no notifications sent yet."])

        return output

    @app.route("/static/<string:group>/<string:filename>", methods=['GET'])
    def static_content(group, filename):
        from flask import make_response

        if group == 'screenshot':
            # Could be sensitive, follow password requirements
            if datastore.data['settings']['application']['password'] and not flask_login.current_user.is_authenticated:
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
                    logger.error(f'Request elements.deflate at "{watch_directory}" but was notfound.')
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
            return send_from_directory("static/{}".format(group), path=filename)
        except FileNotFoundError:
            abort(404)

    @app.route("/edit/<string:uuid>/get-html", methods=['GET'])
    @login_optionally_required
    def watch_get_latest_html(uuid):
        from io import BytesIO
        from flask import send_file
        import brotli

        watch = datastore.data['watching'].get(uuid)
        if watch and watch.history.keys() and os.path.isdir(watch.watch_data_dir):
            latest_filename = list(watch.history.keys())[-1]
            html_fname = os.path.join(watch.watch_data_dir, f"{latest_filename}.html.br")
            with open(html_fname, 'rb') as f:
                if html_fname.endswith('.br'):
                    # Read and decompress the Brotli file
                    decompressed_data = brotli.decompress(f.read())
                else:
                    decompressed_data = f.read()

            buffer = BytesIO(decompressed_data)

            return send_file(buffer, as_attachment=True, download_name=f"{latest_filename}.html", mimetype='text/html')


        # Return a 500 error
        abort(500)

    # Ajax callback
    @app.route("/edit/<string:uuid>/preview-rendered", methods=['POST'])
    @login_optionally_required
    def watch_get_preview_rendered(uuid):
        '''For when viewing the "preview" of the rendered text from inside of Edit'''
        from .processors.text_json_diff import prepare_filter_prevew
        return prepare_filter_prevew(watch_uuid=uuid, datastore=datastore)


    @app.route("/form/add/quickwatch", methods=['POST'])
    @login_optionally_required
    def form_quick_watch_add():
        from changedetectionio import forms
        form = forms.quickWatchForm(request.form)

        if not form.validate():
            for widget, l in form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('index'))

        url = request.form.get('url').strip()
        if datastore.url_exists(url):
            flash(f'Warning, URL {url} already exists', "notice")

        add_paused = request.form.get('edit_and_watch_submit_button') != None
        processor = request.form.get('processor', 'text_json_diff')
        new_uuid = datastore.add_watch(url=url, tag=request.form.get('tags').strip(), extras={'paused': add_paused, 'processor': processor})

        if new_uuid:
            if add_paused:
                flash('Watch added in Paused state, saving will unpause.')
                return redirect(url_for('edit_page', uuid=new_uuid, unpause_on_save=1))
            else:
                # Straight into the queue.
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
                flash("Watch added.")

        return redirect(url_for('index'))



    @app.route("/api/delete", methods=['GET'])
    @login_optionally_required
    def form_delete():
        uuid = request.args.get('uuid')

        if uuid != 'all' and not uuid in datastore.data['watching'].keys():
            flash('The watch by UUID {} does not exist.'.format(uuid), 'error')
            return redirect(url_for('index'))

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        datastore.delete(uuid)
        flash('Deleted.')

        return redirect(url_for('index'))

    @app.route("/api/clone", methods=['GET'])
    @login_optionally_required
    def form_clone():
        uuid = request.args.get('uuid')
        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        new_uuid = datastore.clone(uuid)
        if new_uuid:
            if not datastore.data['watching'].get(uuid).get('paused'):
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=5, item={'uuid': new_uuid}))
            flash('Cloned.')

        return redirect(url_for('index'))

    @app.route("/api/checknow", methods=['GET'])
    @login_optionally_required
    def form_watch_checknow():
        # Forced recheck will skip the 'skip if content is the same' rule (, 'reprocess_existing_data': True})))
        tag = request.args.get('tag')
        uuid = request.args.get('uuid')
        with_errors = request.args.get('with_errors') == "1"

        i = 0

        running_uuids = []
        for t in running_update_threads:
            running_uuids.append(t.current_uuid)

        if uuid:
            if uuid not in running_uuids:
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            i = 1

        elif tag:
            # Items that have this current tag
            for watch_uuid, watch in datastore.data['watching'].items():
                if tag in watch.get('tags', {}):
                    if with_errors and not watch.get('last_error'):
                        continue
                    if watch_uuid not in running_uuids and not datastore.data['watching'][watch_uuid]['paused']:
                        update_q.put(
                            queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid})
                        )
                        i += 1

        else:
            # No tag, no uuid, add everything.
            for watch_uuid, watch in datastore.data['watching'].items():
                if watch_uuid not in running_uuids and not datastore.data['watching'][watch_uuid]['paused']:
                    if with_errors and not watch.get('last_error'):
                        continue
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                    i += 1
        flash(f"{i} watches queued for rechecking.")
        return redirect(url_for('index', tag=tag))

    @app.route("/form/checkbox-operations", methods=['POST'])
    @login_optionally_required
    def form_watch_list_checkbox_operations():
        op = request.form['op']
        uuids = request.form.getlist('uuids')

        if (op == 'delete'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.delete(uuid.strip())
            flash("{} watches deleted".format(len(uuids)))

        elif (op == 'pause'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid.strip()]['paused'] = True
            flash("{} watches paused".format(len(uuids)))

        elif (op == 'unpause'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid.strip()]['paused'] = False
            flash("{} watches unpaused".format(len(uuids)))

        elif (op == 'mark-viewed'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.set_last_viewed(uuid, int(time.time()))
            flash("{} watches updated".format(len(uuids)))

        elif (op == 'mute'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid.strip()]['notification_muted'] = True
            flash("{} watches muted".format(len(uuids)))

        elif (op == 'unmute'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid.strip()]['notification_muted'] = False
            flash("{} watches un-muted".format(len(uuids)))

        elif (op == 'recheck'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    # Recheck and require a full reprocessing
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            flash("{} watches queued for rechecking".format(len(uuids)))

        elif (op == 'clear-errors'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid]["last_error"] = False
            flash(f"{len(uuids)} watches errors cleared")

        elif (op == 'clear-history'):
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.clear_watch_history(uuid)
            flash("{} watches cleared/reset.".format(len(uuids)))

        elif (op == 'notification-default'):
            from changedetectionio.notification import (
                default_notification_format_for_watch
            )
            for uuid in uuids:
                uuid = uuid.strip()
                if datastore.data['watching'].get(uuid):
                    datastore.data['watching'][uuid.strip()]['notification_title'] = None
                    datastore.data['watching'][uuid.strip()]['notification_body'] = None
                    datastore.data['watching'][uuid.strip()]['notification_urls'] = []
                    datastore.data['watching'][uuid.strip()]['notification_format'] = default_notification_format_for_watch
            flash("{} watches set to use default notification settings".format(len(uuids)))

        elif (op == 'assign-tag'):
            op_extradata = request.form.get('op_extradata', '').strip()
            if op_extradata:
                tag_uuid = datastore.add_tag(name=op_extradata)
                if op_extradata and tag_uuid:
                    for uuid in uuids:
                        uuid = uuid.strip()
                        if datastore.data['watching'].get(uuid):
                            # Bug in old versions caused by bad edit page/tag handler
                            if isinstance(datastore.data['watching'][uuid]['tags'], str):
                                datastore.data['watching'][uuid]['tags'] = []

                            datastore.data['watching'][uuid]['tags'].append(tag_uuid)

            flash(f"{len(uuids)} watches were tagged")

        return redirect(url_for('index'))

    @app.route("/api/share-url", methods=['GET'])
    @login_optionally_required
    def form_share_put_watch():
        """Given a watch UUID, upload the info and return a share-link
           the share-link can be imported/added"""
        import requests
        import json
        uuid = request.args.get('uuid')

        # more for testing
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        # copy it to memory as trim off what we dont need (history)
        watch = deepcopy(datastore.data['watching'][uuid])
        # For older versions that are not a @property
        if (watch.get('history')):
            del (watch['history'])

        # for safety/privacy
        for k in list(watch.keys()):
            if k.startswith('notification_'):
                del watch[k]

        for r in['uuid', 'last_checked', 'last_changed']:
            if watch.get(r):
                del (watch[r])

        # Add the global stuff which may have an impact
        watch['ignore_text'] += datastore.data['settings']['application']['global_ignore_text']
        watch['subtractive_selectors'] += datastore.data['settings']['application']['global_subtractive_selectors']

        watch_json = json.dumps(watch)

        try:
            r = requests.request(method="POST",
                                 data={'watch': watch_json},
                                 url="https://changedetection.io/share/share",
                                 headers={'App-Guid': datastore.data['app_guid']})
            res = r.json()

            session['share-link'] = "https://changedetection.io/share/{}".format(res['share_key'])


        except Exception as e:
            logger.error(f"Error sharing -{str(e)}")
            flash("Could not share, something went wrong while communicating with the share server - {}".format(str(e)), 'error')

        # https://changedetection.io/share/VrMv05wpXyQa
        # in the browser - should give you a nice info page - wtf
        # paste in etc
        return redirect(url_for('index'))

    @app.route("/highlight_submit_ignore_url", methods=['POST'])
    @login_optionally_required
    def highlight_submit_ignore_url():
        import re
        mode = request.form.get('mode')
        selection = request.form.get('selection')

        uuid = request.args.get('uuid','')
        if datastore.data["watching"].get(uuid):
            if mode == 'exact':
                for l in selection.splitlines():
                    datastore.data["watching"][uuid]['ignore_text'].append(l.strip())
            elif mode == 'digit-regex':
                for l in selection.splitlines():
                    # Replace any series of numbers with a regex
                    s = re.escape(l.strip())
                    s = re.sub(r'[0-9]+', r'\\d+', s)
                    datastore.data["watching"][uuid]['ignore_text'].append('/' + s + '/')

        return f"<a href={url_for('preview_page', uuid=uuid)}>Click to preview</a>"


    import changedetectionio.blueprint.browser_steps as browser_steps
    app.register_blueprint(browser_steps.construct_blueprint(datastore), url_prefix='/browser-steps')

    import changedetectionio.blueprint.price_data_follower as price_data_follower
    app.register_blueprint(price_data_follower.construct_blueprint(datastore, update_q), url_prefix='/price_data_follower')

    import changedetectionio.blueprint.tags as tags
    app.register_blueprint(tags.construct_blueprint(datastore), url_prefix='/tags')

    import changedetectionio.blueprint.check_proxies as check_proxies
    app.register_blueprint(check_proxies.construct_blueprint(datastore=datastore), url_prefix='/check_proxy')

    import changedetectionio.blueprint.backups as backups
    app.register_blueprint(backups.construct_blueprint(datastore), url_prefix='/backups')


    # @todo handle ctrl break
    ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks).start()
    threading.Thread(target=notification_runner).start()

    # Check for new release version, but not when running in test/build or pytest
    if not os.getenv("GITHUB_REF", False) and not strtobool(os.getenv('DISABLE_VERSION_CHECK', 'no')):
        threading.Thread(target=check_for_new_version).start()

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
                from changedetectionio import notification
                # Fallback to system config if not set
                if not n_object.get('notification_body') and datastore.data['settings']['application'].get('notification_body'):
                    n_object['notification_body'] = datastore.data['settings']['application'].get('notification_body')

                if not n_object.get('notification_title') and datastore.data['settings']['application'].get('notification_title'):
                    n_object['notification_title'] = datastore.data['settings']['application'].get('notification_title')

                if not n_object.get('notification_format') and datastore.data['settings']['application'].get('notification_format'):
                    n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')

                sent_obj = notification.process_notification(n_object, datastore)

            except Exception as e:
                logger.error(f"Watch URL: {n_object['watch_url']}  Error {str(e)}")

                # UUID wont be present when we submit a 'test' from the global settings
                if 'uuid' in n_object:
                    datastore.update_watch(uuid=n_object['uuid'],
                                           update_obj={'last_notification_error': "Notification error detected, goto notification log."})

                log_lines = str(e).splitlines()
                notification_debug_log += log_lines

            # Process notifications
            notification_debug_log+= ["{} - SENDING - {}".format(now.strftime("%Y/%m/%d %H:%M:%S,000"), json.dumps(sent_obj))]
            # Trim the log length
            notification_debug_log = notification_debug_log[-100:]

# Threaded runner, look for new watches to feed into the Queue.
def ticker_thread_check_time_launch_checks():
    import random
    from changedetectionio import update_worker
    proxy_last_called_time = {}

    recheck_time_minimum_seconds = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3))
    logger.debug(f"System env MINIMUM_SECONDS_RECHECK_TIME {recheck_time_minimum_seconds}")

    # Spin up Workers that do the fetching
    # Can be overriden by ENV or use the default settings
    n_workers = int(os.getenv("FETCH_WORKERS", datastore.data['settings']['requests']['workers']))
    for _ in range(n_workers):
        new_worker = update_worker.update_worker(update_q, notification_q, app, datastore)
        running_update_threads.append(new_worker)
        new_worker.start()

    while not app.config.exit.is_set():

        # Get a list of watches by UUID that are currently fetching data
        running_uuids = []
        for t in running_update_threads:
            if t.current_uuid:
                running_uuids.append(t.current_uuid)

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
                    update_q.put(queuedWatchMetaData.PrioritizedItem(priority=priority, item={'uuid': uuid}))

                    # Reset for next time
                    watch.jitter_seconds = 0

        # Wait before checking the list again - saves CPU
        time.sleep(1)

        # Should be low so we can break this out in testing
        app.config.exit.wait(1)
