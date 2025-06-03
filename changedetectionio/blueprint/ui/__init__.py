import time
from flask import Blueprint, request, redirect, url_for, flash, render_template, session
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.blueprint.ui.edit import construct_blueprint as construct_edit_blueprint
from changedetectionio.blueprint.ui.notification import construct_blueprint as construct_notification_blueprint
from changedetectionio.blueprint.ui.views import construct_blueprint as construct_views_blueprint

def _handle_operations(op, uuids, datastore, worker_handler, update_q, queuedWatchMetaData, watch_check_update, extra_data=None, emit_flash=True):
    from flask import request, flash

    if op == 'delete':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.delete(uuid)
        if emit_flash:
            flash(f"{len(uuids)} watches deleted")

    elif op == 'pause':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['paused'] = True
        if emit_flash:
            flash(f"{len(uuids)} watches paused")

    elif op == 'unpause':
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid.strip()]['paused'] = False
        if emit_flash:
            flash(f"{len(uuids)} watches unpaused")

    elif (op == 'mark-viewed'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.set_last_viewed(uuid, int(time.time()))
        if emit_flash:
            flash(f"{len(uuids)} watches updated")

    elif (op == 'mute'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_muted'] = True
        if emit_flash:
            flash(f"{len(uuids)} watches muted")

    elif (op == 'unmute'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_muted'] = False
        if emit_flash:
            flash(f"{len(uuids)} watches un-muted")

    elif (op == 'recheck'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                # Recheck and require a full reprocessing
                worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
        if emit_flash:
            flash(f"{len(uuids)} watches queued for rechecking")

    elif (op == 'clear-errors'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]["last_error"] = False
        if emit_flash:
            flash(f"{len(uuids)} watches errors cleared")

    elif (op == 'clear-history'):
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.clear_watch_history(uuid)
        if emit_flash:
            flash(f"{len(uuids)} watches cleared/reset.")

    elif (op == 'notification-default'):
        from changedetectionio.notification import (
            default_notification_format_for_watch
        )
        for uuid in uuids:
            if datastore.data['watching'].get(uuid):
                datastore.data['watching'][uuid]['notification_title'] = None
                datastore.data['watching'][uuid]['notification_body'] = None
                datastore.data['watching'][uuid]['notification_urls'] = []
                datastore.data['watching'][uuid]['notification_format'] = default_notification_format_for_watch
        if emit_flash:
            flash(f"{len(uuids)} watches set to use default notification settings")

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
        if emit_flash:
            flash(f"{len(uuids)} watches were tagged")

    if uuids:
        for uuid in uuids:
            watch_check_update.send(watch_uuid=uuid)

def construct_blueprint(datastore: ChangeDetectionStore, update_q, worker_handler, queuedWatchMetaData, watch_check_update):
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

    # Import the login decorator
    from changedetectionio.auth_decorator import login_optionally_required

    @ui_blueprint.route("/clear_history/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def clear_watch_history(uuid):
        try:
            datastore.clear_watch_history(uuid)
        except KeyError:
            flash('Watch not found', 'error')
        else:
            flash("Cleared snapshot history for watch {}".format(uuid))
        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/clear_history", methods=['GET', 'POST'])
    @login_optionally_required
    def clear_all_history():
        if request.method == 'POST':
            confirmtext = request.form.get('confirmtext')

            if confirmtext == 'clear':
                for uuid in datastore.data['watching'].keys():
                    datastore.clear_watch_history(uuid)
                flash("Cleared snapshot history for all watches")
            else:
                flash('Incorrect confirmation text.', 'error')

            return redirect(url_for('watchlist.index'))

        output = render_template("clear_all_history.html")
        return output

    # Clear all statuses, so we do not see the 'unviewed' class
    @ui_blueprint.route("/form/mark-all-viewed", methods=['GET'])
    @login_optionally_required
    def mark_all_viewed():
        # Save the current newest history as the most recently viewed
        with_errors = request.args.get('with_errors') == "1"
        for watch_uuid, watch in datastore.data['watching'].items():
            if with_errors and not watch.get('last_error'):
                continue
            datastore.set_last_viewed(watch_uuid, int(time.time()))

        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/delete", methods=['GET'])
    @login_optionally_required
    def form_delete():
        uuid = request.args.get('uuid')

        if uuid != 'all' and not uuid in datastore.data['watching'].keys():
            flash('The watch by UUID {} does not exist.'.format(uuid), 'error')
            return redirect(url_for('watchlist.index'))

        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()
        datastore.delete(uuid)
        flash('Deleted.')

        return redirect(url_for('watchlist.index'))

    @ui_blueprint.route("/clone", methods=['GET'])
    @login_optionally_required
    def form_clone():
        uuid = request.args.get('uuid')
        # More for testing, possible to return the first/only
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

        new_uuid = datastore.clone(uuid)

        if not datastore.data['watching'].get(uuid).get('paused'):
            worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=5, item={'uuid': new_uuid}))

        flash('Cloned, you are editing the new watch.')

        return redirect(url_for("ui.ui_edit.edit_page", uuid=new_uuid))

    @ui_blueprint.route("/checknow", methods=['GET'])
    @login_optionally_required
    def form_watch_checknow():
        # Forced recheck will skip the 'skip if content is the same' rule (, 'reprocess_existing_data': True})))
        tag = request.args.get('tag')
        uuid = request.args.get('uuid')
        with_errors = request.args.get('with_errors') == "1"

        i = 0

        running_uuids = worker_handler.get_running_uuids()

        if uuid:
            if uuid not in running_uuids:
                worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
                i += 1

        else:
            # Recheck all, including muted
            # Get most overdue first
            for k in sorted(datastore.data['watching'].items(), key=lambda item: item[1].get('last_checked', 0)):
                watch_uuid = k[0]
                watch = k[1]
                if not watch['paused']:
                    if watch_uuid not in running_uuids:
                        if with_errors and not watch.get('last_error'):
                            continue

                        if tag != None and tag not in watch['tags']:
                            continue

                        worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                        i += 1

        if i == 1:
            flash("Queued 1 watch for rechecking.")
        if i > 1:
            flash(f"Queued {i} watches for rechecking.")
        if i == 0:
            flash("No watches available to recheck.")

        return redirect(url_for('watchlist.index'))

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
            worker_handler=worker_handler,
            update_q=update_q,
            watch_check_update=watch_check_update,
            op=op,
        )

        return redirect(url_for('watchlist.index'))


    @ui_blueprint.route("/share-url/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def form_share_put_watch(uuid):
        """Given a watch UUID, upload the info and return a share-link
           the share-link can be imported/added"""
        import requests
        import json
        from copy import deepcopy

        # more for testing
        if uuid == 'first':
            uuid = list(datastore.data['watching'].keys()).pop()

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
            flash(f"Could not share, something went wrong while communicating with the share server - {str(e)}", 'error')

        return redirect(url_for('watchlist.index'))

    return ui_blueprint