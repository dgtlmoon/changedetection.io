from flask import Blueprint, request, render_template, flash, url_for, redirect


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
        from changedetectionio.blueprint.tags.form import group_restock_settings_form
        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)
        if not default:
            flash("Tag not found", "error")
            return redirect(url_for('watchlist.index'))

        form = group_restock_settings_form(
                                       formdata=request.form if request.method == 'POST' else None,
                                       data=default,
                                       extra_notification_tokens=datastore.get_unique_notification_tokens_available(),
                                       default_system_settings = datastore.data['settings'],
                                       )

        template_args = {
            'data': default,
            'form': form,
            'watch': default,
            'extra_notification_token_placeholder_info': datastore.get_unique_notification_token_placeholders_available(),
        }

        included_content = {}
        if form.extra_form_content():
            # So that the extra panels can access _helpers.html etc, we set the environment to load from templates/
            # And then render the code from the module
            from jinja2 import Environment, FileSystemLoader
            import importlib.resources
            templates_dir = str(importlib.resources.files("changedetectionio").joinpath('templates'))
            env = Environment(loader=FileSystemLoader(templates_dir))
            template_str = """{% from '_helpers.html' import render_field, render_checkbox_field, render_button %}
        <script>        
            $(document).ready(function () {
                toggleOpacity('#overrides_watch', '#restock-fieldset-price-group', true);
            });
        </script>            
                <fieldset>
                    <div class="pure-control-group">
                        <fieldset class="pure-group">
                        {{ render_checkbox_field(form.overrides_watch) }}
                        <span class="pure-form-message-inline">Used for watches in "Restock & Price detection" mode</span>
                        </fieldset>
                </fieldset>
                """
            template_str += form.extra_form_content()
            template = env.from_string(template_str)
            included_content = template.render(**template_args)

        output = render_template("edit-tag.html",
                                 settings_application=datastore.data['settings']['application'],
                                 extra_tab_content=form.extra_tab_content() if form.extra_tab_content() else None,
                                 extra_form_content=included_content,
                                 **template_args
                                 )

        return output


    @tags_blueprint.route("/edit/<string:uuid>", methods=['POST'])
    @login_optionally_required
    def form_tag_edit_submit(uuid):
        from changedetectionio.blueprint.tags.form import group_restock_settings_form
        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)

        form = group_restock_settings_form(formdata=request.form if request.method == 'POST' else None,
                               data=default,
                               extra_notification_tokens=datastore.get_unique_notification_tokens_available()
                               )
        # @todo subclass form so validation works
        #if not form.validate():
#            for widget, l in form.errors.items():
#                flash(','.join(l), 'error')
#           return redirect(url_for('tags.form_tag_edit_submit', uuid=uuid))

        datastore.data['settings']['application']['tags'][uuid].update(form.data)
        datastore.data['settings']['application']['tags'][uuid]['processor'] = 'restock_diff'
        datastore.needs_write_urgent = True
        flash("Updated")

        return redirect(url_for('tags.tags_overview_page'))


    @tags_blueprint.route("/delete/<string:uuid>", methods=['GET'])
    def form_tag_delete(uuid):
        return redirect(url_for('tags.tags_overview_page'))
    return tags_blueprint
