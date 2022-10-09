#!/usr/bin/python3

import datetime
import os
import queue
import threading
import time
from copy import deepcopy
from threading import Event

import flask_login
import logging
import pytz
import timeago
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
from flask_login import login_required
from flask_restful import abort, Api

from flask_wtf import CSRFProtect

from changedetectionio import html_tools
from changedetectionio.api import api_v1

__version__ = '0.39.20'

datastore = None

# Local
running_update_threads = []
ticker_thread = None

extra_stylesheets = []

update_q = queue.PriorityQueue()

notification_q = queue.Queue()

app = Flask(__name__,
            static_url_path="",
            static_folder="static",
            template_folder="templates")

# Stop browser caching of assets
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

app.config.exit = Event()

app.config['NEW_VERSION_AVAILABLE'] = False

app.config['LOGIN_DISABLED'] = False

#app.config["EXPLAIN_TEMPLATE_LOADING"] = True

# Disables caching of the templates
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.add_extension('jinja2.ext.loopcontrols')
csrf = CSRFProtect()
csrf.init_app(app)

notification_debug_log=[]

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

# We use the whole watch object from the store/JSON so we can see if there's some related status in terms of a thread
# running or something similar.
@app.template_filter('format_last_checked_time')
def _jinja2_filter_datetime(watch_obj, format="%Y-%m-%d %H:%M:%S"):
    # Worker thread tells us which UUID it is currently processing.
    for t in running_update_threads:
        if t.current_uuid == watch_obj['uuid']:
            return '<span class="loader"></span><span> Checking now</span>'

    if watch_obj['last_checked'] == 0:
        return 'Not yet'

    return timeago.format(int(watch_obj['last_checked']), time.time())

@app.template_filter('format_timestamp_timeago')
def _jinja2_filter_datetimestamp(timestamp, format="%Y-%m-%d %H:%M:%S"):
    if timestamp == False:
        return 'Not yet'

    return timeago.format(timestamp, time.time())

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
            raw_salt_pass = datastore.data['settings']['application']['password']

        raw_salt_pass = base64.b64decode(raw_salt_pass)


        salt_from_storage = raw_salt_pass[:32]  # 32 is the length of the salt

        # Use the exact same setup you used to generate the key, but this time put in the password to check
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),  # Convert the password to bytes
            salt_from_storage,
            100000
        )
        new_key =  salt_from_storage + new_key

        return new_key == raw_salt_pass

    pass

def changedetection_app(config=None, datastore_o=None):
    global datastore
    datastore = datastore_o

    # so far just for read-only via tests, but this will be moved eventually to be the main source
    # (instead of the global var)
    app.config['DATASTORE']=datastore_o

    #app.config.update(config or {})

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
        # @todo validate its a URL of this host and use that
        return redirect(url_for('login', next=url_for('index')))

    @app.route('/logout')
    def logout():
        flask_login.logout_user()
        return redirect(url_for('index'))

    # https://github.com/pallets/flask/blob/93dd1709d05a1cf0e886df6223377bdab3b077fb/examples/tutorial/flaskr/__init__.py#L39
    # You can divide up the stuff like this
    @app.route('/login', methods=['GET', 'POST'])
    def login():

        if not datastore.data['settings']['application']['password'] and not os.getenv("SALTED_PASS", False):
            flash("Login not required, no password enabled.", "notice")
            return redirect(url_for('index'))

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
    def do_something_whenever_a_request_comes_in():

        # Disable password login if there is not one set
        # (No password in settings or env var)
        app.config['LOGIN_DISABLED'] = datastore.data['settings']['application']['password'] == False and os.getenv("SALTED_PASS", False) == False

        # Set the auth cookie path if we're running as X-settings/X-Forwarded-Prefix
        if os.getenv('USE_X_SETTINGS') and 'X-Forwarded-Prefix' in request.headers:
            app.config['REMEMBER_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']
            app.config['SESSION_COOKIE_PATH'] = request.headers['X-Forwarded-Prefix']

        # For the RSS path, allow access via a token
        if request.path == '/rss' and request.args.get('token'):
            app_rss_token = datastore.data['settings']['application']['rss_access_token']
            rss_url_token = request.args.get('token')
            if app_rss_token == rss_url_token:
                app.config['LOGIN_DISABLED'] = True

    @app.route("/rss", methods=['GET'])
    @login_required
    def rss():
        from . import diff
        limit_tag = request.args.get('tag')

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []

        # @todo needs a .itemsWithTag() or something - then we can use that in Jinaj2 and throw this away
        for uuid, watch in datastore.data['watching'].items():

            if limit_tag != None:
                # Support for comma separated list of tags.
                for tag_in_watch in watch['tag'].split(','):
                    tag_in_watch = tag_in_watch.strip()
                    if tag_in_watch == limit_tag:
                        watch['uuid'] = uuid
                        sorted_watches.append(watch)

            else:
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

            prev_fname = watch.history[dates[-2]]

            if not watch.viewed:
                # Re #239 - GUID needs to be individual for each event
                # @todo In the future make this a configurable link back (see work on BASE_URL https://github.com/dgtlmoon/changedetection.io/pull/228)
                guid = "{}/{}".format(watch['uuid'], watch.last_changed)
                fe = fg.add_entry()

                # Include a link to the diff page, they will have to login here to see if password protection is enabled.
                # Description is the page you watch, link takes you to the diff JS UI page
                base_url = datastore.data['settings']['application']['base_url']
                if base_url == '':
                    base_url = "<base-url-env-var-not-set>"

                diff_link = {'href': "{}{}".format(base_url, url_for('diff_history_page', uuid=watch['uuid']))}

                fe.link(link=diff_link)

                # @todo watch should be a getter - watch.get('title') (internally if URL else..)

                watch_title = watch.get('title') if watch.get('title') else watch.get('url')
                fe.title(title=watch_title)
                latest_fname = watch.history[dates[-1]]

                html_diff = diff.render_diff(prev_fname, latest_fname, include_equal=False, line_feed_sep="</br>")
                fe.content(content="<html><body><h4>{}</h4>{}</body></html>".format(watch_title, html_diff),
                           type='CDATA')

                fe.guid(guid, permalink=False)
                dt = datetime.datetime.fromtimestamp(int(watch.newest_history_key))
                dt = dt.replace(tzinfo=pytz.UTC)
                fe.pubDate(dt)

        response = make_response(fg.rss_str())
        response.headers.set('Content-Type', 'application/rss+xml;charset=utf-8')
        return response

    @app.route("/", methods=['GET'])
    @login_required
    def index():
        from changedetectionio import forms

        limit_tag = request.args.get('tag')
        # Redirect for the old rss path which used the /?rss=true
        if request.args.get('rss'):
            return redirect(url_for('rss', tag=limit_tag))

        op = request.args.get('op')
        if op:
            uuid = request.args.get('uuid')
            if op == 'pause':
                datastore.data['watching'][uuid]['paused'] ^= True
            elif op == 'mute':
                datastore.data['watching'][uuid]['notification_muted'] ^= True

            datastore.needs_write = True
            return redirect(url_for('index', tag = limit_tag))

        # Sort by last_changed and add the uuid which is usually the key..
        sorted_watches = []
        for uuid, watch in datastore.data['watching'].items():

            if limit_tag != None:
                # Support for comma separated list of tags.
                if watch['tag'] is None:
                    continue
                for tag_in_watch in watch['tag'].split(','):
                    tag_in_watch = tag_in_watch.strip()
                    if tag_in_watch == limit_tag:
                        watch['uuid'] = uuid
                        sorted_watches.append(watch)

            else:
                watch['uuid'] = uuid
                sorted_watches.append(watch)

        existing_tags = datastore.get_all_tags()

        form = forms.quickWatchForm(request.form)
        output = render_template("watch-overview.html",
                                 form=form,
                                 watches=sorted_watches,
                                 tags=existing_tags,
                                 active_tag=limit_tag,
                                 app_rss_token=datastore.data['settings']['application']['rss_access_token'],
                                 has_unviewed=datastore.has_unviewed,
                                 # Don't link to hosting when we're on the hosting environment
                                 hosted_sticky=os.getenv("SALTED_PASS", False) == False,
                                 guid=datastore.data['app_guid'],
                                 queued_uuids=[uuid for p,uuid in update_q.queue])


        if session.get('share-link'):
            del(session['share-link'])
        return output


    # AJAX endpoint for sending a test
    @app.route("/notification/send-test", methods=['POST'])
    @login_required
    def ajax_callback_send_notification_test():

        import apprise
        from .apprise_asset import asset
        apobj = apprise.Apprise(asset=asset)


        # validate URLS
        if not len(request.form['notification_urls'].strip()):
            return make_response({'error': 'No Notification URLs set'}, 400)

        for server_url in request.form['notification_urls'].splitlines():
            if len(server_url.strip()):
                if not apobj.add(server_url):
                    message = '{} is not a valid AppRise URL.'.format(server_url)
                    return make_response({'error': message}, 400)

        try:
            n_object = {'watch_url': request.form['window_url'],
                        'notification_urls': request.form['notification_urls'].splitlines(),
                        'notification_title': request.form['notification_title'].strip(),
                        'notification_body': request.form['notification_body'].strip(),
                        'notification_format': request.form['notification_format'].strip()
                        }
            notification_q.put(n_object)
        except Exception as e:
            return make_response({'error': str(e)}, 400)

        return 'OK'


    @app.route("/clear_history/<string:uuid>", methods=['GET'])
    @login_required
    def clear_watch_history(uuid):
        try:
            datastore.clear_watch_history(uuid)
        except KeyError:
            flash('Watch not found', 'error')
        else:
            flash("Cleared snapshot history for watch {}".format(uuid))

        return redirect(url_for('index'))

    @app.route("/clear_history", methods=['GET', 'POST'])
    @login_required
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


    # If they edited an existing watch, we need to know to reset the current/previous md5 to include
    # the excluded text.
    def get_current_checksum_include_ignore_text(uuid):

        import hashlib

        from changedetectionio import fetch_site_status

        # Get the most recent one
        newest_history_key = datastore.data['watching'][uuid].get('newest_history_key')

        # 0 means that theres only one, so that there should be no 'unviewed' history available
        if newest_history_key == 0:
            newest_history_key = list(datastore.data['watching'][uuid].history.keys())[0]

        if newest_history_key:
            with open(datastore.data['watching'][uuid].history[newest_history_key],
                      encoding='utf-8') as file:
                raw_content = file.read()

                handler = fetch_site_status.perform_site_check(datastore=datastore)
                stripped_content = html_tools.strip_ignore_text(raw_content,
                                                             datastore.data['watching'][uuid]['ignore_text'])

                if datastore.data['settings']['application'].get('ignore_whitespace', False):
                    checksum = hashlib.md5(stripped_content.translate(None, b'\r\n\t ')).hexdigest()
                else:
                    checksum = hashlib.md5(stripped_content).hexdigest()

                return checksum

        return datastore.data['watching'][uuid]['previous_md5']


    @app.route("/edit/<string:uuid>", methods=['GET', 'POST'])
    @login_required
    # https://stackoverflow.com/questions/42984453/wtforms-populate-form-with-data-if-data-exists
    # https://wtforms.readthedocs.io/en/3.0.x/forms/#wtforms.form.Form.populate_obj ?

    def edit_page(uuid):
        from changedetectionio import forms

        using_default_check_time = True
        # More for testing, possible to return the first/only
        if not datastore.data['watching'].keys():
            flash("No watches to edit", "error")
            return redirect(url_for('index'))

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        if not uuid in datastore.data['watching']:
            flash("No watch with the UUID %s found." % (uuid), "error")
            return redirect(url_for('index'))

        # be sure we update with a copy instead of accidently editing the live object by reference
        default = deepcopy(datastore.data['watching'][uuid])

        # Show system wide default if nothing configured
        if all(value == 0 or value == None for value in datastore.data['watching'][uuid]['time_between_check'].values()):
            default['time_between_check'] = deepcopy(datastore.data['settings']['requests']['time_between_check'])

        # Defaults for proxy choice
        if datastore.proxy_list is not None:  # When enabled
            # @todo
            # Radio needs '' not None, or incase that the chosen one no longer exists
            if default['proxy'] is None or not any(default['proxy'] in tup for tup in datastore.proxy_list):
                default['proxy'] = ''

        # proxy_override set to the json/text list of the items
        form = forms.watchForm(formdata=request.form if request.method == 'POST' else None,
                               data=default,
                               )

        if datastore.proxy_list is None:
            # @todo - Couldn't get setattr() etc dynamic addition working, so remove it instead
            del form.proxy
        else:
            form.proxy.choices = [('', 'Default')]
            for p in datastore.proxy_list:
                form.proxy.choices.append(tuple((p, datastore.proxy_list[p]['label'])))


        if request.method == 'POST' and form.validate():
            extra_update_obj = {}

            if request.args.get('unpause_on_save'):
                extra_update_obj['paused'] = False

            # Re #110, if they submit the same as the default value, set it to None, so we continue to follow the default
            # Assume we use the default value, unless something relevant is different, then use the form value
            # values could be None, 0 etc.
            # Set to None unless the next for: says that something is different
            extra_update_obj['time_between_check'] = dict.fromkeys(form.time_between_check.data)
            for k, v in form.time_between_check.data.items():
                if v and v != datastore.data['settings']['requests']['time_between_check'][k]:
                    extra_update_obj['time_between_check'] = form.time_between_check.data
                    using_default_check_time = False
                    break

            # Use the default if its the same as system wide
            if form.fetch_backend.data == datastore.data['settings']['application']['fetch_backend']:
                extra_update_obj['fetch_backend'] = None


             # Ignore text
            form_ignore_text = form.ignore_text.data
            datastore.data['watching'][uuid]['ignore_text'] = form_ignore_text

            # Reset the previous_md5 so we process a new snapshot including stripping ignore text.
            if form_ignore_text:
                if len(datastore.data['watching'][uuid].history):
                    extra_update_obj['previous_md5'] = get_current_checksum_include_ignore_text(uuid=uuid)

            # Reset the previous_md5 so we process a new snapshot including stripping ignore text.
            if form.css_filter.data.strip() != datastore.data['watching'][uuid]['css_filter']:
                if len(datastore.data['watching'][uuid].history):
                    extra_update_obj['previous_md5'] = get_current_checksum_include_ignore_text(uuid=uuid)

            # Be sure proxy value is None
            if datastore.proxy_list is not None and form.data['proxy'] == '':
                extra_update_obj['proxy'] = None

            datastore.data['watching'][uuid].update(form.data)
            datastore.data['watching'][uuid].update(extra_update_obj)

            if request.args.get('unpause_on_save'):
                flash("Updated watch - unpaused!.")
            else:
                flash("Updated watch.")

            # Re #286 - We wait for syncing new data to disk in another thread every 60 seconds
            # But in the case something is added we should save straight away
            datastore.needs_write_urgent = True

            # Queue the watch for immediate recheck, with a higher priority
            update_q.put((1, uuid))

            # Diff page [edit] link should go back to diff page
            if request.args.get("next") and request.args.get("next") == 'diff':
                return redirect(url_for('diff_history_page', uuid=uuid))

            return redirect(url_for('index'))

        else:
            if request.method == 'POST' and not form.validate():
                flash("An error occurred, please see below.", "error")

            visualselector_data_is_ready = datastore.visualselector_data_is_ready(uuid)

            # Only works reliably with Playwright
            visualselector_enabled = os.getenv('PLAYWRIGHT_DRIVER_URL', False) and default['fetch_backend'] == 'html_webdriver'


            output = render_template("edit.html",
                                     uuid=uuid,
                                     watch=datastore.data['watching'][uuid],
                                     form=form,
                                     has_empty_checktime=using_default_check_time,
                                     has_default_notification_urls=True if len(datastore.data['settings']['application']['notification_urls']) else False,
                                     using_global_webdriver_wait=default['webdriver_delay'] is None,
                                     current_base_url=datastore.data['settings']['application']['base_url'],
                                     emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                                     settings_application=datastore.data['settings']['application'],
                                     visualselector_data_is_ready=visualselector_data_is_ready,
                                     visualselector_enabled=visualselector_enabled,
                                     playwright_enabled=os.getenv('PLAYWRIGHT_DRIVER_URL', False)
                                     )

        return output

    @app.route("/settings", methods=['GET', "POST"])
    @login_required
    def settings_page():
        from changedetectionio import content_fetcher, forms

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
                                        data=default
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

        output = render_template("settings.html",
                                 form=form,
                                 current_base_url = datastore.data['settings']['application']['base_url'],
                                 hide_remove_pass=os.getenv("SALTED_PASS", False),
                                 api_key=datastore.data['settings']['application'].get('api_access_token'),
                                 emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                                 settings_application=datastore.data['settings']['application'])

        return output

    @app.route("/import", methods=['GET', "POST"])
    @login_required
    def import_page():
        remaining_urls = []
        if request.method == 'POST':
            from .importer import import_url_list, import_distill_io_json

            # URL List import
            if request.values.get('urls') and len(request.values.get('urls').strip()):
                # Import and push into the queue for immediate update check
                importer = import_url_list()
                importer.run(data=request.values.get('urls'), flash=flash, datastore=datastore)
                for uuid in importer.new_uuids:
                    update_q.put((1, uuid))

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
                    update_q.put((1, uuid))



        # Could be some remaining, or we could be on GET
        output = render_template("import.html",
                                 import_url_list_remaining="\n".join(remaining_urls),
                                 original_distill_json=''
                                 )
        return output

    # Clear all statuses, so we do not see the 'unviewed' class
    @app.route("/form/mark-all-viewed", methods=['GET'])
    @login_required
    def mark_all_viewed():

        # Save the current newest history as the most recently viewed
        for watch_uuid, watch in datastore.data['watching'].items():
            datastore.set_last_viewed(watch_uuid, int(time.time()))

        return redirect(url_for('index'))

    @app.route("/diff/<string:uuid>", methods=['GET'])
    @login_required
    def diff_history_page(uuid):

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        extra_stylesheets = [url_for('static_content', group='styles', filename='diff.css')]
        try:
            watch = datastore.data['watching'][uuid]
        except KeyError:
            flash("No history found for the specified link, bad link?", "error")
            return redirect(url_for('index'))

        history = watch.history
        dates = list(history.keys())

        if len(dates) < 2:
            flash("Not enough saved change detection snapshots to produce a report.", "error")
            return redirect(url_for('index'))

        # Save the current newest history as the most recently viewed
        datastore.set_last_viewed(uuid, time.time())

        newest_file = history[dates[-1]]

        try:
            with open(newest_file, 'r') as f:
                newest_version_file_contents = f.read()
        except Exception as e:
            newest_version_file_contents = "Unable to read {}.\n".format(newest_file)

        previous_version = request.args.get('previous_version')
        try:
            previous_file = history[previous_version]
        except KeyError:
            # Not present, use a default value, the second one in the sorted list.
            previous_file = history[dates[-2]]

        try:
            with open(previous_file, 'r') as f:
                previous_version_file_contents = f.read()
        except Exception as e:
            previous_version_file_contents = "Unable to read {}.\n".format(previous_file)


        screenshot_url = watch.get_screenshot()

        system_uses_webdriver = datastore.data['settings']['application']['fetch_backend'] == 'html_webdriver'

        is_html_webdriver = True if watch.get('fetch_backend') == 'html_webdriver' or (
                    watch.get('fetch_backend', None) is None and system_uses_webdriver) else False

        output = render_template("diff.html",
                                 watch_a=watch,
                                 newest=newest_version_file_contents,
                                 previous=previous_version_file_contents,
                                 extra_stylesheets=extra_stylesheets,
                                 versions=dates[:-1], # All except current/last
                                 uuid=uuid,
                                 newest_version_timestamp=dates[-1],
                                 current_previous_version=str(previous_version),
                                 current_diff_url=watch['url'],
                                 extra_title=" - Diff - {}".format(watch['title'] if watch['title'] else watch['url']),
                                 left_sticky=True,
                                 screenshot=screenshot_url,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_text=watch.get_error_text(),
                                 last_error_screenshot=watch.get_error_snapshot()
                                 )

        return output

    @app.route("/preview/<string:uuid>", methods=['GET'])
    @login_required
    def preview_page(uuid):
        content = []
        ignored_line_numbers = []
        trigger_line_numbers = []

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


        is_html_webdriver = True if watch.get('fetch_backend') == 'html_webdriver' or (
                watch.get('fetch_backend', None) is None and system_uses_webdriver) else False

        # Never requested successfully, but we detected a fetch error
        if datastore.data['watching'][uuid].history_n == 0 and (watch.get_error_text() or watch.get_error_snapshot()):
            flash("Preview unavailable - No fetch/check completed or triggers not reached", "error")
            output = render_template("preview.html",
                                     content=content,
                                     history_n=watch.history_n,
                                     extra_stylesheets=extra_stylesheets,
#                                     current_diff_url=watch['url'],
                                     watch=watch,
                                     uuid=uuid,
                                     is_html_webdriver=is_html_webdriver,
                                     last_error=watch['last_error'],
                                     last_error_text=watch.get_error_text(),
                                     last_error_screenshot=watch.get_error_snapshot())
            return output

        timestamp = list(watch.history.keys())[-1]
        filename = watch.history[timestamp]
        try:
            with open(filename, 'r') as f:
                tmp = f.readlines()

                # Get what needs to be highlighted
                ignore_rules = watch.get('ignore_text', []) + datastore.data['settings']['application']['global_ignore_text']

                # .readlines will keep the \n, but we will parse it here again, in the future tidy this up
                ignored_line_numbers = html_tools.strip_ignore_text(content="".join(tmp),
                                                                    wordlist=ignore_rules,
                                                                    mode='line numbers'
                                                                    )

                trigger_line_numbers = html_tools.strip_ignore_text(content="".join(tmp),
                                                                    wordlist=watch['trigger_text'],
                                                                    mode='line numbers'
                                                                    )
                # Prepare the classes and lines used in the template
                i=0
                for l in tmp:
                    classes=[]
                    i+=1
                    if i in ignored_line_numbers:
                        classes.append('ignored')
                    if i in trigger_line_numbers:
                        classes.append('triggered')
                    content.append({'line': l, 'classes': ' '.join(classes)})

        except Exception as e:
            content.append({'line': "File doesnt exist or unable to read file {}".format(filename), 'classes': ''})

        output = render_template("preview.html",
                                 content=content,
                                 history_n=watch.history_n,
                                 extra_stylesheets=extra_stylesheets,
                                 ignored_line_numbers=ignored_line_numbers,
                                 triggered_line_numbers=trigger_line_numbers,
                                 current_diff_url=watch['url'],
                                 screenshot=watch.get_screenshot(),
                                 watch=watch,
                                 uuid=uuid,
                                 is_html_webdriver=is_html_webdriver,
                                 last_error=watch['last_error'],
                                 last_error_text=watch.get_error_text(),
                                 last_error_screenshot=watch.get_error_snapshot())

        return output

    @app.route("/settings/notification-logs", methods=['GET'])
    @login_required
    def notification_logs():
        global notification_debug_log
        output = render_template("notification-log.html",
                                 logs=notification_debug_log if len(notification_debug_log) else ["Notification logs are empty - no notifications sent yet."])

        return output

    @app.route("/favicon.ico", methods=['GET'])
    def favicon():
        return send_from_directory("static/images", path="favicon.ico")

    # We're good but backups are even better!
    @app.route("/backup", methods=['GET'])
    @login_required
    def get_backup():

        import zipfile
        from pathlib import Path

        # Remove any existing backup file, for now we just keep one file

        for previous_backup_filename in Path(datastore_o.datastore_path).rglob('changedetection-backup-*.zip'):
            os.unlink(previous_backup_filename)

        # create a ZipFile object
        backupname = "changedetection-backup-{}.zip".format(int(time.time()))

        # We only care about UUIDS from the current index file
        uuids = list(datastore.data['watching'].keys())
        backup_filepath = os.path.join(datastore_o.datastore_path, backupname)

        with zipfile.ZipFile(backup_filepath, "w",
                             compression=zipfile.ZIP_DEFLATED,
                             compresslevel=8) as zipObj:

            # Be sure we're written fresh
            datastore.sync_to_json()

            # Add the index
            zipObj.write(os.path.join(datastore_o.datastore_path, "url-watches.json"), arcname="url-watches.json")

            # Add the flask app secret
            zipObj.write(os.path.join(datastore_o.datastore_path, "secret.txt"), arcname="secret.txt")

            # Add any snapshot data we find, use the full path to access the file, but make the file 'relative' in the Zip.
            for txt_file_path in Path(datastore_o.datastore_path).rglob('*.txt'):
                parent_p = txt_file_path.parent
                if parent_p.name in uuids:
                    zipObj.write(txt_file_path,
                                 arcname=str(txt_file_path).replace(datastore_o.datastore_path, ''),
                                 compress_type=zipfile.ZIP_DEFLATED,
                                 compresslevel=8)

            # Create a list file with just the URLs, so it's easier to port somewhere else in the future
            list_file = "url-list.txt"
            with open(os.path.join(datastore_o.datastore_path, list_file), "w") as f:
                for uuid in datastore.data["watching"]:
                    url = datastore.data["watching"][uuid]["url"]
                    f.write("{}\r\n".format(url))
            list_with_tags_file = "url-list-with-tags.txt"
            with open(
                os.path.join(datastore_o.datastore_path, list_with_tags_file), "w"
            ) as f:
                for uuid in datastore.data["watching"]:
                    url = datastore.data["watching"][uuid]["url"]
                    tag = datastore.data["watching"][uuid]["tag"]
                    f.write("{} {}\r\n".format(url, tag))

            # Add it to the Zip
            zipObj.write(
                os.path.join(datastore_o.datastore_path, list_file),
                arcname=list_file,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=8,
            )
            zipObj.write(
                os.path.join(datastore_o.datastore_path, list_with_tags_file),
                arcname=list_with_tags_file,
                compress_type=zipfile.ZIP_DEFLATED,
                compresslevel=8,
            )

        # Send_from_directory needs to be the full absolute path
        return send_from_directory(os.path.abspath(datastore_o.datastore_path), backupname, as_attachment=True)

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
                # set nocache, set content-type
                watch_dir = datastore_o.datastore_path + "/" + filename
                response = make_response(send_from_directory(filename="elements.json", directory=watch_dir, path=watch_dir + "/elements.json"))
                response.headers['Content-type'] = 'application/json'
                response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
                response.headers['Pragma'] = 'no-cache'
                response.headers['Expires'] = 0
                return response

            except FileNotFoundError:
                abort(404)

        # These files should be in our subdirectory
        try:
            return send_from_directory("static/{}".format(group), path=filename)
        except FileNotFoundError:
            abort(404)

    @app.route("/form/add/quickwatch", methods=['POST'])
    @login_required
    def form_quick_watch_add():
        from changedetectionio import forms
        form = forms.quickWatchForm(request.form)

        if not form.validate():
            flash("Error")
            return redirect(url_for('index'))

        url = request.form.get('url').strip()
        if datastore.url_exists(url):
            flash('The URL {} already exists'.format(url), "error")
            return redirect(url_for('index'))

        add_paused = request.form.get('edit_and_watch_submit_button') != None
        new_uuid = datastore.add_watch(url=url, tag=request.form.get('tag').strip(), extras={'paused': add_paused})


        if not add_paused and new_uuid:
            # Straight into the queue.
            update_q.put((1, new_uuid))
            flash("Watch added.")

        if add_paused:
            flash('Watch added in Paused state, saving will unpause.')
            return redirect(url_for('edit_page', uuid=new_uuid, unpause_on_save=1))

        return redirect(url_for('index'))



    @app.route("/api/delete", methods=['GET'])
    @login_required
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
    @login_required
    def form_clone():
        uuid = request.args.get('uuid')
        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        new_uuid = datastore.clone(uuid)
        update_q.put((5, new_uuid))
        flash('Cloned.')

        return redirect(url_for('index'))

    @app.route("/api/checknow", methods=['GET'])
    @login_required
    def form_watch_checknow():

        tag = request.args.get('tag')
        uuid = request.args.get('uuid')
        i = 0

        running_uuids = []
        for t in running_update_threads:
            running_uuids.append(t.current_uuid)

        # @todo check thread is running and skip

        if uuid:
            if uuid not in running_uuids:
                update_q.put((1, uuid))
            i = 1

        elif tag != None:
            # Items that have this current tag
            for watch_uuid, watch in datastore.data['watching'].items():
                if (tag != None and tag in watch['tag']):
                    if watch_uuid not in running_uuids and not datastore.data['watching'][watch_uuid]['paused']:
                        update_q.put((1, watch_uuid))
                        i += 1

        else:
            # No tag, no uuid, add everything.
            for watch_uuid, watch in datastore.data['watching'].items():

                if watch_uuid not in running_uuids and not datastore.data['watching'][watch_uuid]['paused']:
                    update_q.put((1, watch_uuid))
                    i += 1
        flash("{} watches are queued for rechecking.".format(i))
        return redirect(url_for('index', tag=tag))

    @app.route("/form/checkbox-operations", methods=['POST'])
    @login_required
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

        return redirect(url_for('index'))

    @app.route("/api/share-url", methods=['GET'])
    @login_required
    def form_share_put_watch():
        """Given a watch UUID, upload the info and return a share-link
           the share-link can be imported/added"""
        import requests
        import json
        tag = request.args.get('tag')
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
            logging.error("Error sharing -{}".format(str(e)))
            flash("Could not share, something went wrong while communicating with the share server - {}".format(str(e)), 'error')

        # https://changedetection.io/share/VrMv05wpXyQa
        # in the browser - should give you a nice info page - wtf
        # paste in etc
        return redirect(url_for('index'))

    # @todo handle ctrl break
    ticker_thread = threading.Thread(target=ticker_thread_check_time_launch_checks).start()

    threading.Thread(target=notification_runner).start()

    # Check for new release version, but not when running in test/build
    if not os.getenv("GITHUB_REF", False):
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

                sent_obj = notification.process_notification(n_object, datastore)

            except Exception as e:
                logging.error("Watch URL: {}  Error {}".format(n_object['watch_url'], str(e)))

                # UUID wont be present when we submit a 'test' from the global settings
                if 'uuid' in n_object:
                    datastore.update_watch(uuid=n_object['uuid'],
                                           update_obj={'last_notification_error': "Notification error detected, please see logs."})

                log_lines = str(e).splitlines()
                notification_debug_log += log_lines

            # Process notifications
            notification_debug_log+= ["{} - SENDING - {}".format(now.strftime("%Y/%m/%d %H:%M:%S,000"), json.dumps(sent_obj))]
            # Trim the log length
            notification_debug_log = notification_debug_log[-100:]

# Thread runner to check every minute, look for new watches to feed into the Queue.
def ticker_thread_check_time_launch_checks():
    import random
    from changedetectionio import update_worker

    proxy_last_called_time = {}

    recheck_time_minimum_seconds = int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 20))
    print("System env MINIMUM_SECONDS_RECHECK_TIME", recheck_time_minimum_seconds)

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
                watch_uuid_list = datastore.data['watching'].keys()
            except RuntimeError as e:
                # RuntimeError: dictionary changed size during iteration
                time.sleep(0.1)
            else:
                break

        # Re #438 - Don't place more watches in the queue to be checked if the queue is already large
        while update_q.qsize() >= 2000:
            time.sleep(1)


        recheck_time_system_seconds = int(datastore.threshold_seconds)

        # Check for watches outside of the time threshold to put in the thread queue.
        for uuid in watch_uuid_list:
            now = time.time()
            watch = datastore.data['watching'].get(uuid)
            if not watch:
                logging.error("Watch: {} no longer present.".format(uuid))
                continue

            # No need todo further processing if it's paused
            if watch['paused']:
                continue

            # If they supplied an individual entry minutes to threshold.

            watch_threshold_seconds = watch.threshold_seconds()
            threshold = watch_threshold_seconds if watch_threshold_seconds > 0 else recheck_time_system_seconds

            # #580 - Jitter plus/minus amount of time to make the check seem more random to the server
            jitter = datastore.data['settings']['requests'].get('jitter_seconds', 0)
            if jitter > 0:
                if watch.jitter_seconds == 0:
                    watch.jitter_seconds = random.uniform(-abs(jitter), jitter)

            seconds_since_last_recheck = now - watch['last_checked']

            if seconds_since_last_recheck >= (threshold + watch.jitter_seconds) and seconds_since_last_recheck >= recheck_time_minimum_seconds:
                if not uuid in running_uuids and uuid not in [q_uuid for p,q_uuid in update_q.queue]:

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
                                print("> Skipped UUID {} using proxy '{}', not enough time between proxy requests {}s/{}s".format(uuid,
                                                                                                                         watch_proxy,
                                                                                                                         time_since_proxy_used,
                                                                                                                         proxy_list_reuse_time_minimum))
                                continue
                            else:
                                # Record the last used time
                                proxy_last_called_time[watch_proxy] = int(time.time())

                    # Use Epoch time as priority, so we get a "sorted" PriorityQueue, but we can still push a priority 1 into it.
                    priority = int(time.time())
                    print(
                        "> Queued watch UUID {} last checked at {} queued at {:0.2f} priority {} jitter {:0.2f}s, {:0.2f}s since last checked".format(
                            uuid,
                            watch['last_checked'],
                            now,
                            priority,
                            watch.jitter_seconds,
                            now - watch['last_checked']))
                    # Into the queue with you
                    update_q.put((priority, uuid))

                    # Reset for next time
                    watch.jitter_seconds = 0

        # Wait before checking the list again - saves CPU
        time.sleep(1)

        # Should be low so we can break this out in testing
        app.config.exit.wait(1)
