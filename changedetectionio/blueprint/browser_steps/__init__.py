
# HORRIBLE HACK BUT WORKS :-) PR anyone?
#
# Why?
# `browsersteps_playwright_browser_interface.chromium.connect_over_cdp()` will only run once without async()
# - this flask app is not async()
# - A single timeout/keepalive which applies to the session made at .connect_over_cdp()
#
# So it means that we must unfortunately for now just keep a single timer since .connect_over_cdp() was run
# and know when that reaches timeout/keepalive :( when that time is up, restart the connection and tell the user
# that their time is up, insert another coin. (reload)
#
#

from changedetectionio.strtobool import strtobool
from flask import Blueprint, request, make_response
import os

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required
from loguru import logger

browsersteps_sessions = {}
io_interface_context = None


def construct_blueprint(datastore: ChangeDetectionStore):
    browser_steps_blueprint = Blueprint('browser_steps', __name__, template_folder="templates")

    def start_browsersteps_session(watch_uuid):
        from . import nonContext
        from . import browser_steps
        import time
        global browsersteps_sessions
        global io_interface_context


        # We keep the playwright session open for many minutes
        keepalive_seconds = int(os.getenv('BROWSERSTEPS_MINUTES_KEEPALIVE', 10)) * 60

        browsersteps_start_session = {'start_time': time.time()}

        # You can only have one of these running
        # This should be very fine to leave running for the life of the application
        # @idea - Make it global so the pool of watch fetchers can use it also
        if not io_interface_context:
            io_interface_context = nonContext.c_sync_playwright()
            # Start the Playwright context, which is actually a nodejs sub-process and communicates over STDIN/STDOUT pipes
            io_interface_context = io_interface_context.start()

        keepalive_ms = ((keepalive_seconds + 3) * 1000)
        base_url = os.getenv('PLAYWRIGHT_DRIVER_URL', '').strip('"')
        a = "?" if not '?' in base_url else '&'
        base_url += a + f"timeout={keepalive_ms}"

        try:
            browsersteps_start_session['browser'] = io_interface_context.chromium.connect_over_cdp(base_url)
        except Exception as e:
            if 'ECONNREFUSED' in str(e):
                return make_response('Unable to start the Playwright Browser session, is it running?', 401)
            else:
                # Other errors, bad URL syntax, bad reply etc
                return make_response(str(e), 401)

        proxy_id = datastore.get_preferred_proxy_for_watch(uuid=watch_uuid)
        proxy = None
        if proxy_id:
            proxy_url = datastore.proxy_list.get(proxy_id).get('url')
            if proxy_url:

                # Playwright needs separate username and password values
                from urllib.parse import urlparse
                parsed = urlparse(proxy_url)
                proxy = {'server': proxy_url}

                if parsed.username:
                    proxy['username'] = parsed.username

                if parsed.password:
                    proxy['password'] = parsed.password

                logger.debug(f"Browser Steps: UUID {watch_uuid} selected proxy {proxy_url}")

        # Tell Playwright to connect to Chrome and setup a new session via our stepper interface
        browsersteps_start_session['browserstepper'] = browser_steps.browsersteps_live_ui(
            playwright_browser=browsersteps_start_session['browser'],
            proxy=proxy,
            start_url=datastore.data['watching'][watch_uuid].get('url'),
            headers=datastore.data['watching'][watch_uuid].get('headers')
        )

        # For test
        #browsersteps_start_session['browserstepper'].action_goto_url(value="http://example.com?time="+str(time.time()))

        return browsersteps_start_session


    @login_optionally_required
    @browser_steps_blueprint.route("/browsersteps_start_session", methods=['GET'])
    def browsersteps_start_session():
        # A new session was requested, return sessionID

        import uuid
        global browsersteps_sessions

        browsersteps_session_id = str(uuid.uuid4())
        watch_uuid = request.args.get('uuid')

        if not watch_uuid:
            return make_response('No Watch UUID specified', 500)

        logger.debug("Starting connection with playwright")
        logger.debug("browser_steps.py connecting")
        browsersteps_sessions[browsersteps_session_id] = start_browsersteps_session(watch_uuid)
        logger.debug("Starting connection with playwright - done")
        return {'browsersteps_session_id': browsersteps_session_id}

    @login_optionally_required
    @browser_steps_blueprint.route("/browsersteps_image", methods=['GET'])
    def browser_steps_fetch_screenshot_image():
        from flask import (
            make_response,
            request,
            send_from_directory,
        )
        uuid = request.args.get('uuid')
        step_n = int(request.args.get('step_n'))

        watch = datastore.data['watching'].get(uuid)
        filename = f"step_before-{step_n}.jpeg" if request.args.get('type', '') == 'before' else f"step_{step_n}.jpeg"

        if step_n and watch and os.path.isfile(os.path.join(watch.watch_data_dir, filename)):
            response = make_response(send_from_directory(directory=watch.watch_data_dir, path=filename))
            response.headers['Content-type'] = 'image/jpeg'
            response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = 0
            return response

        else:
            return make_response('Unable to fetch image, is the URL correct? does the watch exist? does the step_type-n.jpeg exist?', 401)

    # A request for an action was received
    @login_optionally_required
    @browser_steps_blueprint.route("/browsersteps_update", methods=['POST'])
    def browsersteps_ui_update():
        import base64
        import playwright._impl._errors
        global browsersteps_sessions
        from changedetectionio.blueprint.browser_steps import browser_steps

        remaining =0
        uuid = request.args.get('uuid')

        browsersteps_session_id = request.args.get('browsersteps_session_id')

        if not browsersteps_session_id:
            return make_response('No browsersteps_session_id specified', 500)

        if not browsersteps_sessions.get(browsersteps_session_id):
            return make_response('No session exists under that ID', 500)


        # Actions - step/apply/etc, do the thing and return state
        if request.method == 'POST':
            # @todo - should always be an existing session
            step_operation = request.form.get('operation')
            step_selector = request.form.get('selector')
            step_optional_value = request.form.get('optional_value')
            step_n = int(request.form.get('step_n'))
            is_last_step = strtobool(request.form.get('is_last_step'))

            # @todo try.. accept.. nice errors not popups..
            try:

                browsersteps_sessions[browsersteps_session_id]['browserstepper'].call_action(action_name=step_operation,
                                         selector=step_selector,
                                         optional_value=step_optional_value)

            except Exception as e:
                logger.error(f"Exception when calling step operation {step_operation} {str(e)}")
                # Try to find something of value to give back to the user
                return make_response(str(e).splitlines()[0], 401)

            # Get visual selector ready/update its data (also use the current filter info from the page?)
            # When the last 'apply' button was pressed
            # @todo this adds overhead because the xpath selection is happening twice
            u = browsersteps_sessions[browsersteps_session_id]['browserstepper'].page.url
            if is_last_step and u:
                (screenshot, xpath_data) = browsersteps_sessions[browsersteps_session_id]['browserstepper'].request_visualselector_data()
                watch = datastore.data['watching'].get(uuid)
                if watch:
                    watch.save_screenshot(screenshot=screenshot)
                    watch.save_xpath_data(data=xpath_data)

#        if not this_session.page:
#            cleanup_playwright_session()
#            return make_response('Browser session ran out of time :( Please reload this page.', 401)

        # Screenshots and other info only needed on requesting a step (POST)
        try:
            state = browsersteps_sessions[browsersteps_session_id]['browserstepper'].get_current_state()
        except playwright._impl._api_types.Error as e:
            return make_response("Browser session ran out of time :( Please reload this page."+str(e), 401)

        # Use send_file() which is way faster than read/write loop on bytes
        import json
        from tempfile import mkstemp
        from flask import send_file
        tmp_fd, tmp_file = mkstemp(text=True, suffix=".json", prefix="changedetectionio-")

        output = json.dumps({'screenshot': "data:image/jpeg;base64,{}".format(
            base64.b64encode(state[0]).decode('ascii')),
            'xpath_data': state[1],
            'session_age_start': browsersteps_sessions[browsersteps_session_id]['browserstepper'].age_start,
            'browser_time_remaining': round(remaining)
        })

        with os.fdopen(tmp_fd, 'w') as f:
            f.write(output)

        response = make_response(send_file(path_or_file=tmp_file,
                                           mimetype='application/json; charset=UTF-8',
                                           etag=True))
        # No longer needed
        os.unlink(tmp_file)

        return response

    return browser_steps_blueprint


