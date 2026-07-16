"""
Queue inspection UI.

Surfaces what's currently being processed and what's waiting so users can
make sense of the "Queued size: N" indicator (see issue #4077).

Priority conventions (see uses of PrioritizedItem across the codebase):
  1     - immediate / manual recheck
  5     - clone follow-up
  >100  - scheduler-enqueued (timestamp-based)
"""

from flask import Blueprint, jsonify, redirect, render_template, request, url_for, flash
from flask_babel import gettext
from flask_paginate import Pagination, get_page_parameter

from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


PRIORITY_LABELS = {
    1: "immediate",
    5: "clone",
}


def _priority_label(priority):
    if priority in PRIORITY_LABELS:
        return PRIORITY_LABELS[priority]
    if priority > 100:
        return "scheduled"
    return f"p{priority}"


def _watch_brief(datastore, uuid):
    """Best-effort summary for a watch (placeholder if it's been deleted)."""
    watch = datastore.data['watching'].get(uuid)
    if not watch:
        return {'uuid': uuid, 'title': None, 'url': None, 'gone': True}
    return {
        'uuid': uuid,
        'title': watch.get('title') or watch.get('label') or None,
        'url': watch.get('url'),
        'last_checked': watch.get('last_checked', 0),
        'last_error': watch.get('last_error') or None,
        'paused': watch.get('paused', False),
        'gone': False,
    }


def _per_page(datastore):
    return int(datastore.data['settings']['application'].get('pager_size', 50)) or 50


def _snapshot(datastore, update_q, page=1, per_page=50):
    """Snapshot the queue + worker state into a JSON-friendly dict, paginating queued items."""
    from changedetectionio import worker_pool

    summary = update_q.get_queue_summary()
    running_uuids = worker_pool.get_running_uuids()
    worker_count = worker_pool.get_worker_count()

    offset = max(0, (page - 1) * per_page)
    paged = update_q.get_all_queued_uuids(limit=per_page, offset=offset)

    queued_items = []
    for entry in paged.get('items', []):
        info = _watch_brief(datastore, entry['uuid'])
        info['position'] = entry['position']
        info['priority'] = entry['priority']
        info['priority_label'] = _priority_label(entry['priority'])
        info['enqueued_at'] = entry.get('enqueued_at')
        queued_items.append(info)

    running_items = []
    for uuid in running_uuids:
        info = _watch_brief(datastore, uuid)
        info['started_at'] = worker_pool.get_uuid_started_at(uuid)
        running_items.append(info)
    total_queued = summary.get('total_items', 0)

    return {
        'worker_count': worker_count,
        'running_count': len(running_items),
        'queued_count': total_queued,
        'summary': {
            'immediate': summary.get('immediate_items', 0),
            'clone': summary.get('clone_items', 0),
            'scheduled': summary.get('scheduled_items', 0),
            'priority_breakdown': summary.get('priority_breakdown', {}),
        },
        'running': running_items,
        'queued': queued_items,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total_queued + per_page - 1) // per_page),
    }


def construct_blueprint(datastore: ChangeDetectionStore, update_q):
    queue_blueprint = Blueprint('ui_queue', __name__, template_folder="templates")

    @queue_blueprint.route("/queue", methods=['GET'])
    @login_optionally_required
    def queue_page():
        per_page = _per_page(datastore)
        page = request.args.get(get_page_parameter(), type=int, default=1) or 1
        snapshot = _snapshot(datastore, update_q, page=page, per_page=per_page)

        pagination = Pagination(
            page=page,
            total=snapshot['queued_count'],
            per_page=per_page,
            css_framework="semantic",
            display_msg=gettext('displaying <b>{start} - {end}</b> {record_name} in total <b>{total}</b>'),
            record_name=gettext('queued items'),
        )
        return render_template(
            "queue.html",
            snapshot=snapshot,
            pagination=pagination,
            extra_classes="queue-full-width",
        )

    @queue_blueprint.route("/queue.json", methods=['GET'])
    @login_optionally_required
    def queue_json():
        per_page = _per_page(datastore)
        page = request.args.get(get_page_parameter(), type=int, default=1) or 1
        return jsonify(_snapshot(datastore, update_q, page=page, per_page=per_page))

    @queue_blueprint.route("/queue/clear", methods=['POST'])
    @login_optionally_required
    def queue_clear():
        before = update_q.qsize()
        update_q.clear()
        flash(gettext("Queue cleared ({} items removed).").format(before))
        return redirect(url_for('ui.ui_queue.queue_page'))

    @queue_blueprint.route("/queue/cancel-running", methods=['POST'])
    @login_optionally_required
    def queue_cancel_running():
        """Abort an in-flight check: kill its worker, spawn a replacement, broadcast 'done'."""
        from changedetectionio import worker_pool
        # Deferred to avoid a circular import (flask_app → ui → queue).
        from changedetectionio.flask_app import notification_q, watch_check_update
        from flask import current_app

        uuid = (request.form.get('uuid') or request.values.get('uuid') or '').strip()
        if not uuid:
            return jsonify({'ok': False, 'error': 'missing uuid'}), 400

        result = worker_pool.cancel_running_uuid(
            uuid,
            update_q=update_q,
            notification_q=notification_q,
            app=current_app._get_current_object(),
            datastore=datastore,
        )

        if not result['cancelled']:
            return jsonify({'ok': False, 'error': 'uuid not currently running', **result}), 404

        # Broadcast through the realtime layer so other connected clients drop the row too.
        try:
            watch_check_update.send(watch_uuid=uuid)
        except Exception:
            pass

        return jsonify({'ok': True, **result})

    return queue_blueprint
