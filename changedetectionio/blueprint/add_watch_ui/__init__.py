from flask import Blueprint, render_template, request, jsonify, make_response, redirect, url_for, flash
from flask_babel import gettext
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
        from changedetectionio.model.browser_config import list_visual_browser_choices, default_visual_browser

        # This flow drives a live interactive browser (screenshot + visual selector), so it's only
        # usable when such a browser exists. The sidebar link is already hidden in that case; guard
        # here too for anyone hitting the URL directly.
        browser_choices = list_visual_browser_choices(datastore)
        if not browser_choices:
            flash(gettext("Add a page watch with a browser needs an interactive browser "
                          "(screenshots + visual selector) - none is configured."), 'error')
            return redirect(url_for('watchlist.index'))

        form = forms.quickWatchForm(None)
        # This page drives the live visual selector, so only offer processors that support it.
        # (The watch-list "add" form uses the same field unfiltered.)
        from changedetectionio import processors
        form.processor.choices = processors.available_processors(processor_filter={'supports_visual_selector': True})

        llm_configured = bool(_get_llm_config(datastore))

        return render_template(
            "add-watch-ui.html",
            form=form,
            llm_configured=llm_configured,
            llm_intent_watch_placeholder=LLM_INTENT_WATCH_PLACEHOLDER,
            browser_choices=browser_choices,
            default_browser=default_visual_browser(datastore),
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

        from changedetectionio.model.browser_config import list_visual_browser_choices, default_visual_browser

        # The browser to preview with is chosen by the radio picker on the page. Validate it against
        # the visual-browser list (so a request can't drive an arbitrary/non-visual engine), then
        # resolve the selector to its concrete engine name (a user browser config maps to its
        # base_fetcher; a built-in engine maps to itself). Fall back to the default visual browser.
        selected = (request.args.get('browser') or '').strip()
        allowed = {v for v, _ in list_visual_browser_choices(datastore)}
        if selected not in allowed:
            selected = default_visual_browser(datastore)
        if not selected:
            return make_response('No interactive browser (screenshots + visual selector) is configured', 400)

        _entry, fetcher_name, _cfg = datastore.browser_config_store.engine_and_config(selected)
        logger.debug(f"Add-watch snapshot: fetching '{url}' using selected browser '{selected}' (engine '{fetcher_name}')")

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

        # Optional per-processor previews of what each would read off this page (e.g. restock shows
        # the detected price/stock). Computed once here from the fetched HTML for every processor
        # offered on the page; the client shows the one for the selected processor and swaps on
        # change. Only processors that implement the hook and return something are included.
        previews = {}
        if html:
            from changedetectionio import processors
            for pname, _ in processors.available_processors(processor_filter={'supports_visual_selector': True}):
                preview = processors.get_processor_preview(datastore, pname, html, url=url)
                if preview:
                    previews[pname] = preview

        return jsonify({
            "temporary_uuid": temp_uuid,
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "xpath_data": xpath_data,
            "processor_previews": previews,
        })

    return add_watch_ui_blueprint
