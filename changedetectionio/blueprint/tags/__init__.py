from flask import Blueprint, request, make_response, render_template, flash, url_for, redirect
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    tags_blueprint = Blueprint('tags', __name__, template_folder="templates")

    @tags_blueprint.route("/list", methods=['GET'])
    @login_optionally_required
    def tags_overview_page():
        from .form import SingleTag
        add_form = SingleTag(request.form)
        sorted_tags = sorted(datastore.data['settings']['application'].get('tags').items(), key=lambda x: x[1]['title'])

        from collections import Counter

        tag_count = Counter(tag for watch in datastore.data['watching'].values() if watch.get('tags') for tag in watch['tags'])

        output = render_template("groups-overview.html",
                                 available_tags=sorted_tags,
                                 form=add_form,
                                 tag_count=tag_count
                                 )

        return output

    @tags_blueprint.route("/add", methods=['POST'])
    @login_optionally_required
    def form_tag_add():
        from .form import SingleTag
        add_form = SingleTag(request.form)

        if not add_form.validate():
            for widget, l in add_form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('tags.tags_overview_page'))

        title = request.form.get('name').strip()

        if datastore.tag_exists_by_name(title):
            flash(f'The tag "{title}" already exists', "error")
            return redirect(url_for('tags.tags_overview_page'))

        datastore.add_tag(title)
        flash("Tag added")


        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/mute/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def mute(uuid):
        if datastore.data['settings']['application']['tags'].get(uuid):
            datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = not datastore.data['settings']['application']['tags'][uuid]['notification_muted']
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/delete/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def delete(uuid):
        removed = 0
        # Delete the tag, and any tag reference
        if datastore.data['settings']['application']['tags'].get(uuid):
            del datastore.data['settings']['application']['tags'][uuid]

        for watch_uuid, watch in datastore.data['watching'].items():
            if watch.get('tags') and uuid in watch['tags']:
                removed += 1
                watch['tags'].remove(uuid)

        flash(f"Tag deleted and removed from {removed} watches")
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/unlink/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def unlink(uuid):
        unlinked = 0
        for watch_uuid, watch in datastore.data['watching'].items():
            if watch.get('tags') and uuid in watch['tags']:
                unlinked += 1
                watch['tags'].remove(uuid)

        flash(f"Tag unlinked removed from {unlinked} watches")
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/delete_all", methods=['GET'])
    @login_optionally_required
    def delete_all():
        for watch_uuid, watch in datastore.data['watching'].items():
            watch['tags'] = []
        datastore.data['settings']['application']['tags'] = {}

        flash(f"All tags deleted")
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/edit/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def form_tag_edit(uuid):
        from changedetectionio import forms

        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)

        form = forms.watchForm(formdata=request.form if request.method == 'POST' else None,
                               data=default,
                               )
        form.datastore=datastore # needed?

        output = render_template("edit-tag.html",
                                 data=default,
                                 form=form,
                                 settings_application=datastore.data['settings']['application'],
                                 )

        return output


    @tags_blueprint.route("/edit/<string:uuid>", methods=['POST'])
    @login_optionally_required
    def form_tag_edit_submit(uuid):
        from changedetectionio import forms
        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)

        form = forms.watchForm(formdata=request.form if request.method == 'POST' else None,
                               data=default,
                               )
        # @todo subclass form so validation works
        #if not form.validate():
#            for widget, l in form.errors.items():
#                flash(','.join(l), 'error')
#           return redirect(url_for('tags.form_tag_edit_submit', uuid=uuid))

        datastore.data['settings']['application']['tags'][uuid].update(form.data)
        datastore.needs_write_urgent = True
        flash("Updated")

        return redirect(url_for('tags.tags_overview_page'))


    @tags_blueprint.route("/delete/<string:uuid>", methods=['GET'])
    def form_tag_delete(uuid):
        return redirect(url_for('tags.tags_overview_page'))
    return tags_blueprint
