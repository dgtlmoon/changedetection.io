import time

from blinker import signal
from flask import Blueprint, request, redirect, url_for, flash, render_template, session


from changedetectionio.store import ChangeDetectionStore

def constuct_ui_ajax_blueprint(datastore: ChangeDetectionStore, update_q, running_update_threads, queuedWatchMetaData, watch_check_completed):
    ui_ajax_blueprint = Blueprint('ajax', __name__, template_folder="templates", url_prefix='/ajax')

    # Import the login decorator
    from changedetectionio.auth_decorator import login_optionally_required

    @ui_ajax_blueprint.route("/toggle", methods=['POST'])
    @login_optionally_required
    def ajax_toggler():
        op = request.values.get('op')
        uuid = request.values.get('uuid')
        if op and datastore.data['watching'].get(uuid):
            if op == 'pause':
                datastore.data['watching'][uuid].toggle_pause()
            elif op == 'mute':
                datastore.data['watching'][uuid].toggle_mute()
            elif op == 'recheck':
                update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

            watch_check_completed = signal('watch_check_completed')
            if watch_check_completed:
                watch_check_completed.send(watch_uuid=uuid)

        return 'OK'


    return ui_ajax_blueprint
