import time
import threading
from flask import Blueprint, request, redirect, url_for, flash, render_template, session, current_app
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.blueprint.ui.edit import construct_blueprint as construct_edit_blueprint
from changedetectionio.blueprint.ui.notification import construct_blueprint as construct_notification_blueprint
from changedetectionio.blueprint.ui.views import construct_blueprint as construct_views_blueprint
from changedetectionio.blueprint.ui import diff, preview

def _handle_operations(op, uuids, datastore, worker_pool, update_q, queuedWatchMetaData, watch_check_update, extra_data=None, emit_flash=True):
    from flask import request, flash

    if op == 'delete':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.delete(uuid)
        if emit_flash:
            flash(gettext("{} watches deleted").format(len(uuids)))

    elif op == 'pause':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['paused'] = True
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches paused").format(len(uuids)))

    elif op == 'unpause':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid.strip()]['paused'] = False
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches unpaused").format(len(uuids)))

    elif (op == 'mark-viewed'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.set_last_viewed(uuid, int(time.time()))
        if emit_flash:
            flash(gettext("{} watches updated").format(len(uuids)))

    elif (op == 'mute'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_muted'] = True
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches muted").format(len(uuids)))

    elif (op == 'unmute'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_muted'] = False
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches un-muted").format(len(uuids)))

    elif (op == 'recheck'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                # Recheck and require a full reprocessing
                worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
        if emit_flash:
            flash(gettext("{} watches queued for rechecking").format(len(uuids)))

    elif (op == 'clear-errors'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]["last_error"] = False
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches errors cleared").format(len(uuids)))

    elif (op == 'clear-history'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.clear_watch_history(uuid)
        if emit_flash:
            flash(gettext("{} watches cleared/reset.").format(len(uuids)))

    elif (op == 'notification-default'):
        from changedetectionio.notification import (
            USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
        )
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_title'] = None
                datastore.data['watching'][uuid]['notification_body'] = None
                datastore.data['watching'][uuid]['notification_urls'] = []
                datastore.data['watching'][uuid]['notification_format'] = USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
                datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches set to use default notification settings").format(len(uuids)))

    elif (op == 'assign-tag'):
        op_extradata = extra_data
        if op_extradata:
            tag_uuid = datastore.add_tag(title=op_extradata)
            if op_extradata and tag_uuid:
                for uuid in uuids:
                    if datastore.data['watching'].get(uuid):
                        # Bug in old versions caused by bad edit page/tag handler
                        if isinstance(datastore.data['watching'][uuid]['tags'], str):
                            datastore.data['watching'][uuid]['tags'] = []

                        datastore.data['watching'][uuid]['tags'].append(tag_uuid)
                        datastore.data['watching'][uuid].commit()
        if emit_flash:
            flash(gettext("{} watches were tagged").format(len(uuids)))

    if uuids:
        for uuid in uuids:
            watch_check_update.send(watch_uuid=uuid)

def construct_blueprint(datastore: ChangeDetectionStore, update_q, worker_pool, queuedWatchMetaData, watch_check_update):
    ui_blueprint = Blueprint('ui', __name__, template_folder="templates")
    
    # Register the edit blueprint
    edit_blueprint = construct_edit_blueprint(datastore, update_q, queuedWatchMetaData)
    ui_blueprint.register_blueprint(edit_blueprint)
    
    # Register the notification blueprint
    notification_blueprint = construct_notification_blueprint(datastore)
    ui_blueprint.register_blueprint(notification_blueprint)
    
    # Register the views blueprint
    views_blueprint = construct_views_blueprint(datastore, update_q, queuedWatchMetaData, watch_check_update)
    ui_blueprint.register_blueprint(views_blueprint)

    # Register diff and preview blueprints
    diff_blueprint = diff.construct_blueprint(datastore)
    ui_blueprint.register_blueprint(diff_blueprint)

    preview_blueprint = preview.construct_blueprint(datastore)
    ui_blueprint.register_blueprint(preview_blueprint)

    # Import the login decorator
    from changedetectionio.auth_decorator import login_optionally_required

    @ui_blueprint.route("/clear_history/<uuid_str:uuid>", methods=['GET'])
    @login_optionally_required
    def clear_watch_history(uuid):
        try:
            datastore.clear_watch_history(uuid)
        except KeyError:
            flash(gettext('Watch not found'), 'error')
        else:
            flash(gettext("Cleared snapshot history for watch {}").format(uuid))
        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/clear_history", methods=['GET', 'POST'])
    @login_optionally_required
    def clear_all_history():
        if request.method == 'POST':
            confirmtext = request.form.get('confirmtext')

            if confirmtext == 'clear':
                # Run in background thread to avoid blocking
                def clear_history_background():
                    # Capture UUIDs first to avoid race conditions
                    watch_uuids = list(datastore.data['watching'].keys())
                    logger.info(f"Background: Clearing history for {len(watch_uuids)} watches")

                    for uuid in watch_uuids:
                        try:
                            datastore.clear_watch_history(uuid)
                        except Exception as e:
                            logger.error(f"Error clearing history for watch {uuid}: {e}")

                    logger.info("Background: Completed clearing history")

                # Start daemon thread
                threading.Thread(target=clear_history_background, daemon=True).start()

                flash(gettext("History clearing started in background"))
            else:
                flash(gettext('Incorrect confirmation text.'), 'error')

            return redirect(url_for('watchlist.index'))

        output = render_template("clear_all_history.html")
        return output

    # Clear all statuses, so we do not see the 'unviewed' class
    @ui_blueprint.route("/form/mark-all-viewed", methods=['GET'])
    @login_optionally_required
    def mark_all_viewed():
        # Save the current newest history as the most recently viewed
        with_errors = request.args.get('with_errors') == "1"
        tag_limit = request.args.get('tag')
        now = int(time.time())

        # Mark watches as viewed - use background thread only for large watch counts
        def mark_viewed_impl():
            """Mark watches as viewed - can run synchronously or in background thread."""
            marked_count = 0
            try:
                for watch_uuid, watch in datastore.data['watching'].items():
                    if with_errors and not watch.get('last_error'):
                        continue

                    if tag_limit and (not watch.get('tags') or tag_limit not in watch['tags']):
                        continue

                    datastore.set_last_viewed(watch_uuid, now)
                    marked_count += 1

                logger.info(f"Marking complete: {marked_count} watches marked as viewed")
            except Exception as e:
                logger.error(f"Error marking as viewed: {e}")

        # For small watch counts (< 10), run synchronously to avoid race conditions in tests
        # For larger counts, use background thread to avoid blocking the UI
        watch_count = len(datastore.data['watching'])
        if watch_count < 10:
            # Run synchronously for small watch counts
            mark_viewed_impl()
        else:
            # Start background thread for large watch counts
            thread = threading.Thread(target=mark_viewed_impl, daemon=True)
            thread.start()

        return redirect(url_for('watchlist.index', tag=tag_limit))

    @ui_blueprint.route("/delete", methods=['GET'])
    @login_optionally_required
    def form_delete():
        uuid = request.args.get('uuid')
        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        if uuid != 'all' and not uuid in datastore.data['watching'].keys():
            flash(gettext('The watch by UUID {} does not exist.').format(uuid), 'error')
            return redirect(url_for('watchlist.index'))

        datastore.delete(uuid)
        flash(gettext('Deleted.'))

        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/clone", methods=['GET'])
    @login_optionally_required
    def form_clone():
        uuid = request.args.get('uuid')

        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        new_uuid = datastore.clone(uuid)

        if not datastore.data['watching'].get(uuid).get('paused'):
            worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=5, item={'uuid': new_uuid}))

        flash(gettext('Cloned, you are editing the new watch.'))

        return redirect(url_for("ui.ui_edit.edit_page", uuid=new_uuid))

    @ui_blueprint.route("/checknow", methods=['GET'])
    @login_optionally_required
    def form_watch_checknow():
        # Forced recheck will skip the 'skip if content is the same' rule (, 'reprocess_existing_data': True})))
        tag = request.args.get('tag')
        uuid = request.args.get('uuid')
        with_errors = request.args.get('with_errors') == "1"

        if uuid:
            # Single watch - check if already queued or running
            if worker_pool.is_watch_running(uuid) or uuid in update_q.get_queued_uuids():
                flash(gettext("Watch is already queued or being checked."))
            else:
                worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
                flash(gettext("Queued 1 watch for rechecking."))
        else:
            # Multiple watches - first count how many need to be queued
            watches_to_queue = []
            for k in sorted(datastore.data['watching'].items(), key=lambda item: item[1].get('last_checked', 0)):
                watch_uuid = k[0]
                watch = k[1]
                if not watch['paused'] and watch_uuid:
                    if with_errors and not watch.get('last_error'):
                        continue
                    if tag != None and tag not in watch['tags']:
                        continue
                    watches_to_queue.append(watch_uuid)

            # If less than 20 watches, queue synchronously for immediate feedback
            if len(watches_to_queue) < 20:
                # Get already queued/running UUIDs once (efficient)
                queued_uuids = set(update_q.get_queued_uuids())
                running_uuids = set(worker_pool.get_running_uuids())

                # Filter out watches that are already queued or running
                watches_to_queue_filtered = []
                for watch_uuid in watches_to_queue:
                    if watch_uuid not in queued_uuids and watch_uuid not in running_uuids:
                        watches_to_queue_filtered.append(watch_uuid)

                # Queue only the filtered watches
                for watch_uuid in watches_to_queue_filtered:
                    worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))

                # Provide feedback about skipped watches
                skipped_count = len(watches_to_queue) - len(watches_to_queue_filtered)
                if skipped_count > 0:
                    flash(gettext("Queued {} watches for rechecking ({} already queued or running).").format(
                        len(watches_to_queue_filtered), skipped_count))
                else:
                    if len(watches_to_queue_filtered) == 1:
                        flash(gettext("Queued 1 watch for rechecking."))
                    else:
                        flash(gettext("Queued {} watches for rechecking.").format(len(watches_to_queue_filtered)))
            else:
                # 20+ watches - queue in background thread to avoid blocking HTTP response
                # Capture queued/running state before background thread
                queued_uuids = set(update_q.get_queued_uuids())
                running_uuids = set(worker_pool.get_running_uuids())

                def queue_watches_background():
                    """Background thread to queue watches - discarded after completion."""
                    try:
                        queued_count = 0
                        skipped_count = 0
                        for watch_uuid in watches_to_queue:
                            # Check if already queued or running (state captured at start)
                            if watch_uuid not in queued_uuids and watch_uuid not in running_uuids:
                                worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                                queued_count += 1
                            else:
                                skipped_count += 1

                        logger.info(f"Background queueing complete: {queued_count} watches queued, {skipped_count} skipped (already queued/running)")
                    except Exception as e:
                        logger.error(f"Error in background queueing: {e}")

                # Start background thread and return immediately
                thread = threading.Thread(target=queue_watches_background, daemon=True, name="QueueWatches-Background")
                thread.start()

                # Return immediately with approximate message
                flash(gettext("Queueing watches for rechecking in background..."))

        return redirect(url_for('watchlist.index', **({'tag': tag} if tag else {})))

    @ui_blueprint.route("/form/checkbox-operations", methods=['POST'])
    @login_optionally_required
    def form_watch_list_checkbox_operations():
        op = request.form['op']
        uuids = [u.strip() for u in request.form.getlist('uuids') if u]
        extra_data = request.form.get('op_extradata', '').strip()
        _handle_operations(
            datastore=datastore,
            extra_data=extra_data,
            queuedWatchMetaData=queuedWatchMetaData,
            uuids=uuids,
            worker_pool=worker_pool,
            update_q=update_q,
            watch_check_update=watch_check_update,
            op=op,
        )

        return redirect(url_for('watchlist.index'))


    @ui_blueprint.route("/share-url/<uuid_str:uuid>", methods=['GET'])
    @login_optionally_required
    def form_share_put_watch(uuid):
        """Given a watch UUID, upload the info and return a share-link
           the share-link can be imported/added"""
        import requests
        import json
        from copy import deepcopy


        # copy it to memory as trim off what we dont need (history)
        watch = deepcopy(datastore.data['watching'].get(uuid))
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

            # Add to the flask session
            session['share-link'] = f"https://changedetection.io/share/{res['share_key']}"


        except Exception as e:
            logger.error(f"Error sharing -{str(e)}")
            flash(gettext("Could not share, something went wrong while communicating with the share server - {}").format(str(e)), 'error')

        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/language/auto-detect", methods=['GET'])
    def delete_locale_language_session_var_if_it_exists():
        """Clear the session locale preference to auto-detect from browser Accept-Language header"""
        if 'locale' in session:
            session.pop('locale', None)
            # Refresh Flask-Babel to clear cached locale
            from flask_babel import refresh
            refresh()
            flash(gettext("Language set to auto-detect from browser"))

        # Check if there's a redirect parameter to return to the same page
        redirect_url = request.args.get('redirect')

        # If redirect is provided and safe, use it
        from changedetectionio.is_safe_url import is_safe_url
        if redirect_url and is_safe_url(redirect_url, current_app):
            return redirect(redirect_url)

        # Otherwise redirect to watchlist
        return redirect(url_for('watchlist.index'))

    return ui_blueprint