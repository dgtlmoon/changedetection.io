import time
from flask import Blueprint, request, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import worker_pool


def run_preloaded_first_check(datastore, uuid):
    """Run the watch's chosen processor once against the snapshot the Add Watch page already
    fetched (parked as preload-fetch.json + screenshot + xpath in the watch dir), producing
    the first history snapshot WITHOUT any network IO.

    Processors are fast and CPU-only here, so we run them inline on submit. Best-effort:
    any failure (or no preload present) returns False and leaves the watch without history,
    so a normal queued check will populate it instead. Returns True if a snapshot was written.
    """
    from changedetectionio.processors import get_processor_module
    from changedetectionio import html_tools

    watch = datastore.data['watching'].get(uuid)
    if not watch:
        return False

    try:
        processor_module = get_processor_module(watch.get('processor', 'text_json_diff'))
        if not processor_module:
            return False

        handler = processor_module.perform_site_check(datastore=datastore, watch_uuid=uuid)

        # Populate the fetcher from the parked snapshot instead of hitting the network.
        if not handler._consume_preloaded_fetch():
            return False

        changed_detected, update_obj, contents = handler.run_changedetection(watch=watch)

        # Mirror the worker's first-snapshot save path (the parts that apply with no network).
        timestamp = int(time.time())
        update_obj['content-type'] = str(handler.fetcher.get_all_headers().get('content-type', '') or "").lower()
        update_obj['last_error'] = False
        update_obj['last_checked'] = timestamp
        watch.reset_watch_edited_flag()
        datastore.update_watch(uuid=uuid, update_obj=update_obj)

        watch.save_history_blob(contents=contents,
                                timestamp=timestamp,
                                snapshot_id=update_obj.get('previous_md5', 'none'))
        if handler.fetcher.content:
            watch.save_last_fetched_html(timestamp=timestamp, contents=handler.fetcher.content)

        # Page title is shown in the list / used in notifications.
        try:
            if 'html' in update_obj.get('content-type', ''):
                page_title = html_tools.extract_title(data=handler.fetcher.content)
                if page_title:
                    datastore.update_watch(uuid=uuid, update_obj={'page_title': page_title.strip()[:2000]})
        except Exception as e:
            logger.debug(f"Add Watch preloaded first-check: title extraction failed for {uuid}: {e}")

        logger.info(f"Add Watch: created first snapshot for {uuid} from preloaded fetch (no network)")
        return True

    except Exception as e:
        # Any processor error (empty text, no matching filters, etc.) - fall back to a normal check.
        logger.warning(f"Add Watch: preloaded first-check failed for {uuid}, falling back to a normal check: {e}")
        return False


def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData, watch_check_update):
    views_blueprint = Blueprint('ui_views', __name__, template_folder="../ui/templates")

    @views_blueprint.route("/form/add/quickwatch", methods=['POST'])
    @login_optionally_required
    def form_quick_watch_add():
        from changedetectionio import forms
        form = forms.quickWatchForm(request.form)

        if not form.validate():
            for widget, l in form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('watchlist.index'))

        url = request.form.get('url').strip()
        if datastore.url_exists(url):
            flash(gettext('Warning, URL {} already exists').format(url), "notice")

        add_paused = request.form.get('edit_and_watch_submit_button') != None
        from changedetectionio import processors
        processor = request.form.get('processor', processors.get_default_processor())
        llm_intent = request.form.get('llm_intent', '').strip()
        extras = {'paused': add_paused, 'processor': processor}
        if llm_intent:
            extras['llm_intent'] = llm_intent

        # The Add-Watch-with-a-browser page posts the chosen interactive browser as fetch_backend so
        # the created watch keeps using it. Validate against the visual-browser list (a form-only
        # value, but never trust the client) before persisting it onto the watch.
        fetch_backend = request.form.get('fetch_backend', '').strip()
        if fetch_backend:
            from changedetectionio.model.browser_config import list_visual_browser_choices
            if fetch_backend in {v for v, _ in list_visual_browser_choices(datastore)}:
                extras['fetch_backend'] = fetch_backend

        # Filters picked with the Add Watch visual selector ("by element" mode)
        include_filters = [l.strip() for l in request.form.get('include_filters', '').split('\n') if l.strip()]
        if include_filters:
            extras['include_filters'] = include_filters

        # If a live preview was fetched on the Add Watch page, promote that snapshot
        # (screenshot + xpath) into the new watch instead of re-fetching. Works for both
        # "Watch" and "Edit & Watch"; falls back to a normal add if the snapshot expired.
        temporary_uuid = request.form.get('temporary_uuid', '').strip()
        new_uuid = datastore.make_temporary_watch_active_watch(
            temp_uuid=temporary_uuid,
            url=url,
            tag=request.form.get('tags', '').strip(),
            extras=extras,
        )

        if new_uuid:
            # If the Add Watch page already fetched a snapshot, run the processor now (no network)
            # to create the first history snapshot. Returns False if there was no preload or it failed.
            created_first_snapshot = run_preloaded_first_check(datastore, new_uuid)

            if add_paused:
                flash(gettext('Watch added in Paused state, saving will unpause.'))
                return redirect(url_for('ui.ui_edit.edit_page', uuid=new_uuid, unpause_on_save=1, tag=request.args.get('tag')))
            else:
                # Only queue a network check if we couldn't build the first snapshot from the
                # preloaded fetch - otherwise the watch is already populated.
                if not created_first_snapshot:
                    worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
                flash(gettext("Watch added."))

        return redirect(url_for('watchlist.index', tag=request.args.get('tag','')))

    return views_blueprint
