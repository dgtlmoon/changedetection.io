"""Quick Event Entry Blueprint for rapid event creation."""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext

from changedetectionio import worker_handler
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    """Construct the quick event entry blueprint."""
    quick_event_blueprint = Blueprint(
        'quick_event',
        __name__,
        template_folder="templates"
    )

    @quick_event_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def quick_entry_page():
        """Render the quick event entry page."""
        from changedetectionio import forms

        form = forms.QuickEventForm()
        form.tags.datastore = datastore

        # Get available tags for the dropdown
        tags = datastore.data['settings']['application'].get('tags', {})
        tags_list = [(uuid, tag.get('title', '')) for uuid, tag in tags.items() if tag.get('title')]
        tags_list.sort(key=lambda x: x[1].lower())

        return render_template(
            "quick_event_entry.html",
            form=form,
            tags_list=tags_list,
        )

    @quick_event_blueprint.route("/add", methods=['POST'])
    @login_optionally_required
    def form_quick_event_add():
        """Handle quick event form submission."""
        from changedetectionio import forms

        form = forms.QuickEventForm(request.form)
        form.tags.datastore = datastore

        if not form.validate():
            for widget, errors in form.errors.items():
                flash(','.join(errors), 'error')
            return redirect(url_for('quick_event.quick_entry_page'))

        url = request.form.get('url', '').strip()
        if not url:
            flash(gettext('URL is required'), 'error')
            return redirect(url_for('quick_event.quick_entry_page'))

        # Check for duplicate URL
        if datastore.url_exists(url):
            flash(gettext('Warning, URL {} already exists').format(url), "notice")

        # Determine if "Add & Open Settings" was clicked
        open_settings = request.form.get('add_and_open_settings') is not None

        # Collect manual entry fields if provided
        manual_title = request.form.get('event_name', '').strip()
        manual_artist = request.form.get('artist', '').strip()
        manual_venue = request.form.get('venue', '').strip()
        manual_date = request.form.get('event_date', '').strip()
        manual_time = request.form.get('event_time', '').strip()

        # Check auto-extract option
        auto_extract = request.form.get('auto_extract') == 'on'

        # Get selected tags (can be comma-separated or multiselect)
        tags_value = request.form.get('tags', '').strip()

        # Build extras dict
        extras = {
            'paused': open_settings,  # Paused if opening settings
            'processor': 'restock_diff',  # Default processor for events
        }

        # If manual fields are provided, add them to extras
        if manual_title:
            extras['title'] = manual_title
        if manual_artist:
            extras['artist'] = manual_artist
        if manual_venue:
            extras['venue'] = manual_venue
        if manual_date:
            extras['event_date'] = manual_date
        if manual_time:
            extras['event_time'] = manual_time

        # Set auto-extract flag
        if auto_extract:
            extras['auto_extract_on_first_check'] = True

        # Create the watch/event
        new_uuid = datastore.add_watch(
            url=url,
            tag=tags_value,
            extras=extras
        )

        if new_uuid:
            if open_settings:
                flash(gettext('Event added in Paused state, saving will unpause.'))
                return redirect(url_for('ui.ui_edit.edit_page', uuid=new_uuid, unpause_on_save=1))
            else:
                # Queue for immediate check
                worker_handler.queue_item_async_safe(
                    update_q,
                    queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid})
                )
                flash(gettext("Event added and first check queued."))

        return redirect(url_for('watchlist.index'))

    return quick_event_blueprint
