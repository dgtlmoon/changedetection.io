from flask import Blueprint, render_template, request, jsonify, make_response
from loguru import logger

from changedetectionio import forms
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def construct_blueprint(datastore: ChangeDetectionStore):
    add_watch_ui_blueprint = Blueprint('add_watch_ui', __name__, template_folder="templates", static_folder="static")

    @add_watch_ui_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def add_watch_ui_index():
        from changedetectionio.llm.evaluator import get_llm_config as _get_llm_config
        from changedetectionio.llm.ui_strings import LLM_INTENT_WATCH_PLACEHOLDER

        form = forms.quickWatchForm(None)
        llm_configured = bool(_get_llm_config(datastore))

        return render_template(
            "add-watch-ui.html",
            form=form,
            llm_configured=llm_configured,
            llm_intent_watch_placeholder=LLM_INTENT_WATCH_PLACEHOLDER,
        )

    @add_watch_ui_blueprint.route("/snapshot", methods=['GET'])
    @login_optionally_required
    def add_watch_ui_snapshot():
        """One-shot live fetch of an arbitrary URL for the Add Watch visual selector.

        Reuses the same browser machinery as Browser Steps (browsersteps_live_ui +
        the dedicated async loop) but without needing a persisted watch - we just
        connect, "Goto site", grab the screenshot + xpath element data, then tear
        the browser down again. Element selection then happens client-side on the
        returned data, exactly like the watch Edit page's visual selector.
        """
        import base64
        from changedetectionio.blueprint.browser_steps import (
            run_async_in_browser_loop,
            _close_session_resources,
            acquire_browser_for_fetcher,
        )
        from changedetectionio.browser_steps.browser_steps import browsersteps_live_ui

        # Opportunistically sweep snapshots that were fetched but never saved.
        datastore.cleanup_temporary_watches()

        url = (request.args.get('url') or '').strip()
        if not url or not url.lower().startswith(('http://', 'https://')):
            return make_response('Please enter a valid http(s):// URL', 400)

        # Use whatever fetcher the application is configured to use by default
        # (e.g. CloakBrowser, Playwright/sockpuppet) so the preview matches real checks.
        fetcher_name = datastore.data['settings']['application'].get('fetch_backend', 'html_requests')
        logger.debug(f"Add-watch snapshot: fetching '{url}' using system default fetcher '{fetcher_name}'")

        async def _fetch_snapshot():
            keepalive_ms = 30 * 1000
            browser, playwright_context = await acquire_browser_for_fetcher(
                fetcher_name, proxy=None, keepalive_ms=keepalive_ms
            )

            stepper = browsersteps_live_ui(playwright_browser=browser, proxy=None, start_url=url)
            session = {'browserstepper': stepper, 'browser': browser, 'playwright_context': playwright_context}
            try:
                await stepper.connect(proxy=None)
                await stepper.call_action(action_name="Goto site", selector=None, optional_value=None)
                (screenshot, xpath_data) = await stepper.get_current_state()
                # Also grab the rendered HTML so the processor can run on submit without
                # re-fetching - this is the input the html->text conversion runs against.
                html = None
                try:
                    html = await stepper.page.content()
                except Exception as e:
                    logger.warning(f"Add-watch snapshot: could not capture page HTML for {url}: {e}")
                return (screenshot, xpath_data, html)
            finally:
                await _close_session_resources(session, label=' for add-watch snapshot')

        try:
            (screenshot, xpath_data, html) = run_async_in_browser_loop(_fetch_snapshot())
        except Exception as e:
            logger.error(f"Add-watch snapshot fetch failed for {url}: {e}")
            if 'ECONNREFUSED' in str(e):
                return make_response('Unable to start the Playwright Browser session, is sockpuppetbrowser running? '
                                     'The live preview needs a fetcher that supports Javascript and screenshots.', 502)
            return make_response(str(e).splitlines()[0] if str(e) else 'Could not fetch the page', 502)

        if not screenshot:
            return make_response('Could not capture a screenshot for that URL', 502)

        # Park the freshly-fetched data in final watch on-disk format so that, if the user
        # clicks Watch / Edit & Watch, we can promote it into a real watch with a single
        # rename() instead of fetching the page all over again.
        import os, json, zlib, uuid as uuid_builder
        temp_uuid = str(uuid_builder.uuid4())
        temp_dir = datastore.get_temporary_watch_dir(temp_uuid)
        try:
            os.makedirs(temp_dir, exist_ok=True)
            with open(os.path.join(temp_dir, "last-screenshot.png"), 'wb') as f:
                f.write(screenshot)
            with open(os.path.join(temp_dir, "elements.deflate"), 'wb') as f:
                f.write(zlib.compress(json.dumps(xpath_data).encode()))
            # The fetch result the processor will run against on submit (one-shot, consumed
            # by difference_detection_processor.call_browser). Only written when we got HTML.
            if html:
                with open(os.path.join(temp_dir, "preload-fetch.json"), 'w', encoding='utf-8') as f:
                    json.dump({"content": html, "status_code": 200,
                               "headers": {"content-type": "text/html"}}, f)
        except Exception as e:
            logger.error(f"Add-watch snapshot: could not park temporary data for {url}: {e}")
            temp_uuid = None

        return jsonify({
            "temporary_uuid": temp_uuid,
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "xpath_data": xpath_data,
        })

    return add_watch_ui_blueprint
