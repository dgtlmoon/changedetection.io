import asyncio
import os
import threading

from flask import Blueprint, render_template, request, jsonify, make_response, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger

from changedetectionio import forms
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def _run_coro_blocking(coro):
    """Run an async coroutine to completion from a sync Flask handler, on its own event loop in a
    dedicated thread. Content fetchers (Playwright etc.) manage their own async lifecycle inside
    run(); giving them a fresh isolated loop keeps them off the request thread and avoids clashing
    with any existing loop - the same "own loop per thread" model the async workers use."""
    box = {}

    def _runner():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            box['value'] = loop.run_until_complete(coro)
        except BaseException as e:  # noqa: BLE001 - re-raised on the caller's thread below
            box['error'] = e
        finally:
            loop.close()

    t = threading.Thread(target=_runner, name='AddWatchSnapshotFetch', daemon=True)
    t.start()
    t.join()
    if 'error' in box:
        raise box['error']
    return box['value']


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

        Drives the SAME content fetcher a real watch check uses (no persisted watch needed): we
        instantiate the resolved browser engine, inject the selected browser_config, run it, and
        read back its screenshot + xpath element data + rendered HTML. Element selection then
        happens client-side on that data, exactly like the watch Edit page's visual selector.

        Using the content fetcher directly (rather than the Browser Steps live machinery) means the
        preview applies the FULL browser profile - viewport / locale / timezone / browser_type /
        User-Agent - and matches exactly what a saved watch will fetch.
        """
        import base64
        from requests.structures import CaseInsensitiveDict
        from changedetectionio import content_fetchers

        # Opportunistically sweep snapshots that were fetched but never saved.
        datastore.cleanup_temporary_watches()

        url = (request.args.get('url') or '').strip()
        if not url or not url.lower().startswith(('http://', 'https://')):
            return make_response('Please enter a valid http(s):// URL', 400)

        from changedetectionio.model.browser_config import list_visual_browser_choices, default_visual_browser

        # The browser to preview with is chosen by the radio picker on the page. Validate it against
        # the visual-browser list (so a request can't drive an arbitrary/non-visual engine), then
        # resolve the selector to its concrete engine name + FetcherConfig (a user browser config
        # maps to its base_fetcher; a built-in engine maps to itself).
        selected = (request.args.get('browser') or '').strip()
        allowed = {v for v, _ in list_visual_browser_choices(datastore)}
        if selected not in allowed:
            selected = default_visual_browser(datastore)
        if not selected:
            return make_response('No interactive browser (screenshots + visual selector) is configured', 400)

        _entry, fetcher_name, browser_config = datastore.browser_config_store.engine_and_config(selected)
        logger.debug(f"Add-watch snapshot: fetching '{url}' using selected browser '{selected}' "
                     f"(engine '{fetcher_name}', viewport {getattr(browser_config, 'viewport_width', None)}x"
                     f"{getattr(browser_config, 'viewport_height', None)})")

        fetcher_class = getattr(content_fetchers, fetcher_name, None)
        if fetcher_class is None:
            return make_response(f"Unknown browser engine '{fetcher_name}'", 400)

        # Instantiate + drive the fetcher the same way difference_detection_processor.call_browser
        # does, minus the persisted-watch plumbing. The fetcher's run() manages its own browser
        # lifecycle and populates .screenshot / .xpath_data / .content.
        fetcher = fetcher_class(proxy_override=None, custom_browser_connection_url=None, screenshot_format='JPEG')
        fetcher.backend_name = fetcher_name
        fetcher.browser_config = browser_config

        request_headers = CaseInsensitiveDict()
        if fetcher.browser_config:
            fetcher.browser_config.apply_user_agent(request_headers)
        request_headers.update(datastore.get_all_base_headers())

        try:
            _run_coro_blocking(fetcher.run(
                url=url,
                request_headers=request_headers,
                request_method='GET',
                request_body=None,
                fetch_favicon=False,          # not needed for the preview
                empty_pages_are_a_change=True, # be lenient - previewing, not change-detecting
                ignore_status_codes=True,      # show whatever the page returns
                # Timeout comes from the browser profile (default 45s), not any plain html_requests
                # setting - this flow only ever drives screenshot-capable browsers.
                timeout=browser_config.timeout,
            ))
        except Exception as e:
            logger.error(f"Add-watch snapshot fetch failed for {url}: {e}")
            if 'ECONNREFUSED' in str(e):
                return make_response('Unable to start the Browser session - is your Chrome/Playwright '
                                     'browser (e.g. sockpuppetbrowser) running? The live preview needs a '
                                     'browser that supports Javascript and screenshots.', 502)
            return make_response(str(e).splitlines()[0] if str(e) else 'Could not fetch the page', 502)

        screenshot = fetcher.screenshot
        xpath_data = fetcher.xpath_data
        html = fetcher.content

        if not screenshot:
            return make_response('Could not capture a screenshot for that URL', 502)

        # Park the freshly-fetched data in final watch on-disk format so that, if the user
        # clicks Watch / Edit & Watch, we can promote it into a real watch with a single
        # rename() instead of fetching the page all over again.
        import json, zlib, uuid as uuid_builder  # os is imported at module level
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
