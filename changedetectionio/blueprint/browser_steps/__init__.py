
from distutils.util import strtobool
from flask import Blueprint, request, make_response
from flask_login import login_required
import os
import logging

from changedetectionio.store import ChangeDetectionStore

browsersteps_live_ui_o = {}
browsersteps_playwright_browser_interface = None
browsersteps_playwright_browser_interface_browser = None

def construct_blueprint(datastore: ChangeDetectionStore):

    browser_steps_blueprint = Blueprint('browser_steps', __name__, template_folder="templates")

    @login_required
    @browser_steps_blueprint.route("/browsersteps_update", methods=['GET', 'POST'])
    def browsersteps_ui_update():
        import base64
        import json
        import playwright._impl._api_types
        from changedetectionio.blueprint.browser_steps import browser_steps

        global browsersteps_live_ui_o
        global browsersteps_playwright_browser_interface_browser
        global browsersteps_playwright_browser_interface

        step_n = None
        uuid = request.args.get('uuid')

        browsersteps_session_id = request.args.get('browsersteps_session_id')

        if not browsersteps_session_id:
            return make_response('No browsersteps_session_id specified', 500)

        this_session = browsersteps_live_ui_o.get(browsersteps_session_id)
        if this_session and this_session.has_expired:
            del browsersteps_live_ui_o[browsersteps_session_id]
            return make_response('Browser session expired, please reload the Browser Steps interface', 500)

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
                this_session.call_action(action_name=step_operation,
                                         selector=step_selector,
                                         optional_value=step_optional_value)
            except playwright._impl._api_types.TimeoutError as e:
                print("Element wasnt found :-(", step_operation)
                # but this isnt always true

                # return make_response('The element did not appear, was the selector/CSS/xPath correct? Does it exist?', 401)

            # Get visual selector ready/update its data (also use the current filter info from the page?)
            # When the last 'apply' button was pressed
            # @todo
            if is_last_step:
                (screenshot, xpath_data) = this_session.request_visualselector_data()
                datastore.save_screenshot(watch_uuid=uuid, screenshot=screenshot)
                datastore.save_xpath_data(watch_uuid=uuid, data=xpath_data)

        # Setup interface
        if request.method == 'GET':
            if not browsersteps_playwright_browser_interface:
                logging.debug("browser_steps.py connecting")
                from playwright.sync_api import sync_playwright
                browsersteps_playwright_browser_interface = sync_playwright().start()

                # browsersteps_playwright_browser_interface_browser = browsersteps_playwright_browser_interface.chromium.connect_over_cdp("ws://127.0.0.1:3000?keepalive={}&timeout=600000&blockAds=1".format(str(int(100000))))
                browsersteps_playwright_browser_interface_browser = browsersteps_playwright_browser_interface.chromium.launch()

            if not browsersteps_live_ui_o.get(browsersteps_session_id):
                # Boot up a new session
                browsersteps_live_ui_o[browsersteps_session_id] = browser_steps.browsersteps_live_ui(
                    browsersteps_playwright_browser_interface_browser)
                this_session = browsersteps_live_ui_o[browsersteps_session_id]

        state = this_session.get_current_state()
        p = {'screenshot': "data:image/png;base64,{}".format(
            base64.b64encode(state[0]).decode('ascii')),
            'xpath_data': state[1],
            'session_age_start': this_session.age_start
        }

        # Update files for Visual Selector tool
        with open(os.path.join(datastore.datastore_path, uuid, "last-screenshot.png"), 'wb') as f:
            f.write(state[0])

        with open(os.path.join(datastore.datastore_path, uuid, "elements.json"), 'w') as f:
            f.write(json.dumps(state[1], indent=1, ensure_ascii=False))

        # @todo BSON/binary JSON, faster xfer, OR pick it off the disk
        return p

    return browser_steps_blueprint