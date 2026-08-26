from flask import Blueprint, render_template, request, jsonify, make_response, flash, redirect, url_for
from flask_babel import gettext
from loguru import logger

from changedetectionio import forms
from changedetectionio.auth_decorator import login_optionally_required
from . import browser_config
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.validate_url import is_fetch_url_allowed


def construct_blueprint(datastore: ChangeDetectionStore):
    add_watch_ui_blueprint = Blueprint('add_watch_ui', __name__, template_folder="templates", static_folder="static")

    @add_watch_ui_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def add_watch_ui_index():
        from changedetectionio.llm.evaluator import get_llm_config as _get_llm_config
        from changedetectionio.llm.ui_strings import LLM_INTENT_WATCH_PLACEHOLDER

        # Same gate that hides the sidebar link (sidebar-nav.html): with no browser that can
        # render a preview there is nothing for the visual selector to work on, so bounce
        # direct navigation rather than serving a page whose only outcome is an error.
        if not browser_config.has_visual_browser(datastore):
            flash(gettext("Adding a watch with a browser needs an interactive browser "
                          "(screenshots + element data) - none is configured."), 'error')
            return redirect(url_for('watchlist.index'))

        form = forms.quickWatchForm(None)
        llm_configured = bool(_get_llm_config(datastore))

        # Start on the browser the live preview would actually use
        form.fetch_backend.data = browser_config.default_visual_browser(datastore)

        return render_template(
            "add-watch-ui.html",
            form=form,
            llm_configured=llm_configured,
            llm_intent_watch_placeholder=LLM_INTENT_WATCH_PLACEHOLDER,
            # Listed but not selectable (the system default when it can't render a preview)
            unusable_browsers=browser_config.unusable_values(datastore),
            system_default_browser=browser_config.system_default_description(datastore),
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

        # This endpoint makes the server-side browser fetch an arbitrary URL and returns the
        # rendered result (screenshot + xpath element data) straight back in the HTTP response, so
        # it is a direct SSRF-with-exfiltration primitive if left unvalidated. It used to only
        # check startswith('http://', 'https://'), which skipped the private-IP gate AND the
        # backslash/parser-differential rejection of GHSA-rph4-96w6-q594 (GHSA-56fq-63vj-9992).
        # Note this fetch never reaches difference_detection_processor.call_browser(), so it gets
        # no gating from there - it has to validate for itself.
        url = (request.args.get('url') or '').strip()
        ok, reason = is_fetch_url_allowed(url)
        if not ok:
            logger.warning(f"Add-watch snapshot: refused '{url}' - {reason}")
            return make_response(reason, 400)

        # Which browser to preview with. The page posts the one picked in its browser list;
        # with nothing asked for we fall back to whatever it would have preselected.
        # Either way it has to be able to render a preview - the plain HTTP client
        # produces no screenshot and no element data, so previewing with it is pointless
        # (and it used to be the silent default here, see the system-default bug).
        fetcher_name = (request.args.get('fetch_backend') or '').strip() or browser_config.default_visual_browser(datastore)
        if not fetcher_name or not browser_config.is_visual_capable(fetcher_name, datastore):
            logger.warning(f"Add-watch snapshot: refused browser '{fetcher_name}' for '{url}'")
            return make_response('No interactive browser available that can render a live preview '
                                 '(needs screenshots + element data)', 400)

        # acquire_browser_for_fetcher() looks the name up as a fetcher class, so 'system'
        # has to be collapsed to the real backend first or a fetcher that launches its own
        # browser would be skipped in favour of the CDP endpoint.
        resolved_fetcher = browser_config.resolve_backend(fetcher_name, datastore)
        logger.debug(f"Add-watch snapshot: fetching '{url}' using '{fetcher_name}' (resolved: '{resolved_fetcher}')")

        async def _fetch_snapshot():
            keepalive_ms = 30 * 1000
            browser, playwright_context = await acquire_browser_for_fetcher(
                resolved_fetcher, proxy=None, keepalive_ms=keepalive_ms
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
            # This directory becomes the new watch's data_dir on submit, so the watch's own
            # settings file is where the previewing browser belongs: record it here and the
            # saved watch checks with the browser that actually rendered this snapshot,
            # instead of falling back to a system default that may not even do screenshots.
            # Read back by make_temporary_watch_active_watch(); commit() then rewrites it in full.
            with open(os.path.join(temp_dir, "watch.json"), 'w', encoding='utf-8') as f:
                json.dump({"fetch_backend": fetcher_name}, f)
        except Exception as e:
            logger.error(f"Add-watch snapshot: could not park temporary data for {url}: {e}")
            temp_uuid = None

        return jsonify({
            "temporary_uuid": temp_uuid,
            "screenshot": f"data:image/jpeg;base64,{base64.b64encode(screenshot).decode('ascii')}",
            "xpath_data": xpath_data,
        })

    return add_watch_ui_blueprint
