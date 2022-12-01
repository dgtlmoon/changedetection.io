
# HORRIBLE HACK BUT WORKS :-) PR anyone?
#
# Why?
# `browsersteps_playwright_browser_interface.chromium.connect_over_cdp()` will only run once without async()
# - this flask app is not async()
# - browserless has a single timeout/keepalive which applies to the session made at .connect_over_cdp()
#
# So it means that we must unfortunately for now just keep a single timer since .connect_over_cdp() was run
# and know when that reaches timeout/keepalive :( when that time is up, restart the connection and tell the user
# that their time is up, insert another coin. (reload)
#
# Bigger picture
# - It's horrible that we have this click+wait deal, some nice socket.io solution using something similar
# to what the browserless debug UI already gives us would be smarter..
#
# OR
# - Some API call that should be hacked into browserless or playwright that we can "/api/bump-keepalive/{session_id}/60"
# So we can tell it that we need more time (run this on each action)
#
# OR
# - use multiprocessing to bump this over to its own process and add some transport layer (queue/pipes)

from distutils.util import strtobool
from flask import Blueprint, request, make_response
from flask_login import login_required
import os
import logging
from changedetectionio.store import ChangeDetectionStore

browsersteps_live_ui_o = {}
browsersteps_playwright_browser_interface = None
browsersteps_playwright_browser_interface_browser = None
browsersteps_playwright_browser_interface_context = None
browsersteps_playwright_browser_interface_end_time = None
browsersteps_playwright_browser_interface_start_time = None

def cleanup_playwright_session():

    global browsersteps_live_ui_o
    global browsersteps_playwright_browser_interface
    global browsersteps_playwright_browser_interface_browser
    global browsersteps_playwright_browser_interface_context
    global browsersteps_playwright_browser_interface_end_time
    global browsersteps_playwright_browser_interface_start_time

    browsersteps_live_ui_o = {}
    browsersteps_playwright_browser_interface = None
    browsersteps_playwright_browser_interface_browser = None
    browsersteps_playwright_browser_interface_end_time = None
    browsersteps_playwright_browser_interface_start_time = None

    print("Cleaning up old playwright session because time was up, calling .goodbye()")
    try:
        browsersteps_playwright_browser_interface_context.goodbye()
    except Exception as e:
        print ("Got exception in shutdown, probably OK")
        print (str(e))

    browsersteps_playwright_browser_interface_context = None

    print ("Cleaning up old playwright session because time was up - done")

def construct_blueprint(datastore: ChangeDetectionStore):

    browser_steps_blueprint = Blueprint('browser_steps', __name__, template_folder="templates")

    @login_required
    @browser_steps_blueprint.route("/browsersteps_update", methods=['GET', 'POST'])
    def browsersteps_ui_update():
        import base64
        import playwright._impl._api_types
        import time

        from changedetectionio.blueprint.browser_steps import browser_steps

        global browsersteps_live_ui_o, browsersteps_playwright_browser_interface_end_time
        global browsersteps_playwright_browser_interface_browser
        global browsersteps_playwright_browser_interface
        global browsersteps_playwright_browser_interface_start_time

        step_n = None
        remaining =0
        uuid = request.args.get('uuid')

        browsersteps_session_id = request.args.get('browsersteps_session_id')

        if not browsersteps_session_id:
            return make_response('No browsersteps_session_id specified', 500)

        # Because we don't "really" run in a context manager ( we make the playwright interface global/long-living )
        # We need to manage the shutdown when the time is up
        if browsersteps_playwright_browser_interface_end_time:
            remaining = browsersteps_playwright_browser_interface_end_time-time.time()
            if browsersteps_playwright_browser_interface_end_time and remaining <= 0:
                cleanup_playwright_session()
                return make_response('Browser session expired, please reload the Browser Steps interface', 401)

        # Actions - step/apply/etc, do the thing and return state
        if request.method == 'POST':
            # @todo - should always be an existing session
            step_operation = request.form.get('operation')
            step_selector = request.form.get('selector')
            step_optional_value = request.form.get('optional_value')
            step_n = int(request.form.get('step_n'))
            is_last_step = strtobool(request.form.get('is_last_step'))

            if step_operation == 'Goto site':
                step_operation = 'goto_url'
                step_optional_value = None
                step_selector = datastore.data['watching'][uuid].get('url')

            # @todo try.. accept.. nice errors not popups..
            try:

                this_session = browsersteps_live_ui_o.get(browsersteps_session_id)
                if not this_session:
                    print("Browser exited")
                    return make_response('Browser session ran out of time :( Please reload this page.', 401)

                this_session.call_action(action_name=step_operation,
                                         selector=step_selector,
                                         optional_value=step_optional_value)

            except Exception as e:
                print("Exception when calling step operation", step_operation, str(e))
                # Try to find something of value to give back to the user
                return make_response(str(e).splitlines()[0], 401)

            # Get visual selector ready/update its data (also use the current filter info from the page?)
            # When the last 'apply' button was pressed
            # @todo this adds overhead because the xpath selection is happening twice
            u = this_session.page.url
            if is_last_step and u:
                (screenshot, xpath_data) = this_session.request_visualselector_data()
                datastore.save_screenshot(watch_uuid=uuid, screenshot=screenshot)
                datastore.save_xpath_data(watch_uuid=uuid, data=xpath_data)

        # Setup interface
        if request.method == 'GET':

            if not browsersteps_playwright_browser_interface:
                print("Starting connection with playwright")
                logging.debug("browser_steps.py connecting")

                global browsersteps_playwright_browser_interface_context
                from . import nonContext
                browsersteps_playwright_browser_interface_context = nonContext.c_sync_playwright()
                browsersteps_playwright_browser_interface = browsersteps_playwright_browser_interface_context.start()

                time.sleep(1)
                # At 20 minutes, some other variable is closing it
                # @todo find out what it is and set it
                seconds_keepalive = int(os.getenv('BROWSERSTEPS_MINUTES_KEEPALIVE', 10)) * 60

                # keep it alive for 10 seconds more than we advertise, sometimes it helps to keep it shutting down cleanly
                keepalive = "&timeout={}".format(((seconds_keepalive+3) * 1000))
                try:
                    browsersteps_playwright_browser_interface_browser = browsersteps_playwright_browser_interface.chromium.connect_over_cdp(
                        os.getenv('PLAYWRIGHT_DRIVER_URL', '') + keepalive)
                except Exception as e:
                    if 'ECONNREFUSED' in str(e):
                        return make_response('Unable to start the Playwright session properly, is it running?', 401)

                browsersteps_playwright_browser_interface_end_time = time.time() + (seconds_keepalive-3)
                print("Starting connection with playwright - done")

            if not browsersteps_live_ui_o.get(browsersteps_session_id):
                # Boot up a new session
                proxy_id = datastore.get_preferred_proxy_for_watch(uuid=uuid)
                proxy = None
                if proxy_id:
                    proxy_url = datastore.proxy_list.get(proxy_id).get('url')
                    if proxy_url:
                        proxy = {'server': proxy_url}
                        print("Browser Steps: UUID {} Using proxy {}".format(uuid, proxy_url))

                # Begin the new "Playwright Context" that re-uses the playwright interface
                # Each session is a "Playwright Context" as a list, that uses the playwright interface
                browsersteps_live_ui_o[browsersteps_session_id] = browser_steps.browsersteps_live_ui(
                    playwright_browser=browsersteps_playwright_browser_interface_browser,
                    proxy=proxy)
                this_session = browsersteps_live_ui_o[browsersteps_session_id]

        if not this_session.page:
            cleanup_playwright_session()
            return make_response('Browser session ran out of time :( Please reload this page.', 401)

        response = None

        if request.method == 'POST':
            # Screenshots and other info only needed on requesting a step (POST)
            try:
                state = this_session.get_current_state()
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
                'session_age_start': this_session.age_start,
                'browser_time_remaining': round(remaining)
            })

            with os.fdopen(tmp_fd, 'w') as f:
                f.write(output)

            response = make_response(send_file(path_or_file=tmp_file,
                                               mimetype='application/json; charset=UTF-8',
                                               etag=True))
            # No longer needed
            os.unlink(tmp_file)

        elif request.method == 'GET':
            # Just enough to get the session rolling, it will call for goto-site via POST next
            response = make_response({
                'session_age_start': this_session.age_start,
                'browser_time_remaining': round(remaining)
            })

        return response

    return browser_steps_blueprint


