
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
import json
import hashlib
from flask import Response
import asyncio
import threading

def run_async_in_browser_loop(coro):
    """Run async coroutine using the existing async worker event loop"""
    from changedetectionio import worker_handler
    
    # Use the existing async worker event loop instead of creating a new one
    if worker_handler.USE_ASYNC_WORKERS and worker_handler.async_loop and not worker_handler.async_loop.is_closed():
        logger.debug("Browser steps using existing async worker event loop")
        future = asyncio.run_coroutine_threadsafe(coro, worker_handler.async_loop)
        return future.result()
    else:
        # Fallback: create a new event loop (for sync workers or if async loop not available)
        logger.debug("Browser steps creating temporary event loop")
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

def construct_blueprint(datastore: ChangeDetectionStore):
    browser_steps_blueprint = Blueprint('browser_steps', __name__, template_folder="templates")

    async def start_browsersteps_session(watch_uuid):
        from . import browser_steps
        import time
        from playwright.async_api import async_playwright

        # We keep the playwright session open for many minutes
        keepalive_seconds = int(os.getenv('BROWSERSTEPS_MINUTES_KEEPALIVE', 10)) * 60

        browsersteps_start_session = {'start_time': time.time()}

        # Create a new async playwright instance for browser steps
        playwright_instance = async_playwright()
        playwright_context = await playwright_instance.start()

        keepalive_ms = ((keepalive_seconds + 3) * 1000)
        base_url = os.getenv('PLAYWRIGHT_DRIVER_URL', '').strip('"')
        a = "?" if not '?' in base_url else '&'
        base_url += a + f"timeout={keepalive_ms}"

        browser = await playwright_context.chromium.connect_over_cdp(base_url, timeout=keepalive_ms)
        browsersteps_start_session['browser'] = browser
        browsersteps_start_session['playwright_context'] = playwright_context

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
        browserstepper = browser_steps.browsersteps_live_ui(
            playwright_browser=browser,
            proxy=proxy,
            start_url=datastore.data['watching'][watch_uuid].link,
            headers=datastore.data['watching'][watch_uuid].get('headers')
        )
        
        # Initialize the async connection
        await browserstepper.connect(proxy=proxy)
        
        browsersteps_start_session['browserstepper'] = browserstepper

        # For test
        #await browsersteps_start_session['browserstepper'].action_goto_url(value="http://example.com?time="+str(time.time()))

        return browsersteps_start_session


    @login_optionally_required
    @browser_steps_blueprint.route("/browsersteps_start_session", methods=['GET'])
    def browsersteps_start_session():
        # A new session was requested, return sessionID
        import asyncio
        import uuid
        browsersteps_session_id = str(uuid.uuid4())
        watch_uuid = request.args.get('uuid')

        if not watch_uuid:
            return make_response('No Watch UUID specified', 500)

        logger.debug("Starting connection with playwright")
        logger.debug("browser_steps.py connecting")

        try:
            # Run the async function in the dedicated browser steps event loop
            browsersteps_sessions[browsersteps_session_id] = run_async_in_browser_loop(
                start_browsersteps_session(watch_uuid)
            )
        except Exception as e:
            if 'ECONNREFUSED' in str(e):
                return make_response('Unable to start the Playwright Browser session, is sockpuppetbrowser running? Network configuration is OK?', 401)
            else:
                # Other errors, bad URL syntax, bad reply etc
                return make_response(str(e), 401)

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
        from changedetectionio.blueprint.browser_steps import browser_steps

        remaining =0
        uuid = request.args.get('uuid')

        browsersteps_session_id = request.args.get('browsersteps_session_id')

        if not browsersteps_session_id:
            return make_response('No browsersteps_session_id specified', 500)

        if not browsersteps_sessions.get(browsersteps_session_id):
            return make_response('No session exists under that ID', 500)

        is_last_step = False
        # Actions - step/apply/etc, do the thing and return state
        if request.method == 'POST':
            # @todo - should always be an existing session
            step_operation = request.form.get('operation')
            step_selector = request.form.get('selector')
            step_optional_value = request.form.get('optional_value')
            is_last_step = strtobool(request.form.get('is_last_step'))

            try:
                # Run the async call_action method in the dedicated browser steps event loop
                run_async_in_browser_loop(
                    browsersteps_sessions[browsersteps_session_id]['browserstepper'].call_action(
                        action_name=step_operation,
                        selector=step_selector,
                        optional_value=step_optional_value
                    )
                )

            except Exception as e:
                logger.error(f"Exception when calling step operation {step_operation} {str(e)}")
                # Try to find something of value to give back to the user
                return make_response(str(e).splitlines()[0], 401)


#        if not this_session.page:
#            cleanup_playwright_session()
#            return make_response('Browser session ran out of time :( Please reload this page.', 401)

        # Screenshots and other info only needed on requesting a step (POST)
        try:
            # Run the async get_current_state method in the dedicated browser steps event loop
            (screenshot, xpath_data) = run_async_in_browser_loop(
                browsersteps_sessions[browsersteps_session_id]['browserstepper'].get_current_state()
            )
                
            if is_last_step:
                watch = datastore.data['watching'].get(uuid)
                u = browsersteps_sessions[browsersteps_session_id]['browserstepper'].page.url
                if watch and u:
                    watch.save_screenshot(screenshot=screenshot)
                    watch.save_xpath_data(data=xpath_data)

        except playwright._impl._api_types.Error as e:
            return make_response("Browser session ran out of time :( Please reload this page."+str(e), 401)
        except Exception as e:
            return make_response("Error fetching screenshot and element data - " + str(e), 401)

        # SEND THIS BACK TO THE BROWSER
        output = {
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "xpath_data": xpath_data,
            "session_age_start": browsersteps_sessions[browsersteps_session_id]['browserstepper'].age_start,
            "browser_time_remaining": round(remaining)
        }
        json_data = json.dumps(output)

        # Generate an ETag (hash of the response body)
        etag_hash = hashlib.md5(json_data.encode('utf-8')).hexdigest()

        # Create the response with ETag
        response = Response(json_data, mimetype="application/json; charset=UTF-8")
        response.set_etag(etag_hash)

        return response

    return browser_steps_blueprint


