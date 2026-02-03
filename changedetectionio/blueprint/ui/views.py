from flask import Blueprint, request, redirect, url_for, flash
from flask_babel import gettext
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio import worker_pool


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
        processor = request.form.get('processor', 'text_json_diff')
        new_uuid = datastore.add_watch(url=url, tag=request.form.get('tags').strip(), extras={'paused': add_paused, 'processor': processor})

        if new_uuid:
            if add_paused:
                flash(gettext('Watch added in Paused state, saving will unpause.'))
                return redirect(url_for('ui.ui_edit.edit_page', uuid=new_uuid, unpause_on_save=1, tag=request.args.get('tag')))
            else:
                # Straight into the queue.
                worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
                flash(gettext("Watch added."))

        return redirect(url_for('watchlist.index', tag=request.args.get('tag','')))

    return views_blueprint