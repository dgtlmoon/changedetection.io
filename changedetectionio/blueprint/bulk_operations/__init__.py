"""Bulk Operations Blueprint - CSV import/export and progress tracking for events."""
import csv
import io
import time

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_babel import gettext
from loguru import logger

from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def construct_blueprint(datastore: ChangeDetectionStore, update_q, queuedWatchMetaData):
    bulk_ops_blueprint = Blueprint('bulk_operations', __name__, template_folder="templates")

    # Track bulk operation progress in session
    _progress_tracker = {}

    @bulk_ops_blueprint.route("/bulk", methods=['GET'])
    @login_optionally_required
    def bulk_operations_page():
        """Main bulk operations page with import/export options."""
        from changedetectionio import forms
        form = forms.importForm(formdata=request.form if request.method == 'POST' else None)

        return render_template(
            "bulk_operations.html",
            form=form,
            total_watches=len(datastore.data['watching']),
            tags=list(datastore.data['settings']['application'].get('tags', {}).items())
        )

    @bulk_ops_blueprint.route("/bulk/import/csv", methods=['POST'])
    @login_optionally_required
    def import_events_csv():
        """Import events from CSV file.

        Expected columns: url, tags, event_name, artist, venue
        """
        if 'csv_file' not in request.files:
            flash(gettext('No CSV file provided'), 'error')
            return redirect(url_for('bulk_operations.bulk_operations_page'))

        file = request.files['csv_file']
        if file.filename == '':
            flash(gettext('No file selected'), 'error')
            return redirect(url_for('bulk_operations.bulk_operations_page'))

        if not file.filename.lower().endswith('.csv'):
            flash(gettext('File must be a CSV file'), 'error')
            return redirect(url_for('bulk_operations.bulk_operations_page'))

        try:
            # Read CSV file
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)

            # Normalize column names (lowercase, strip whitespace)
            if reader.fieldnames:
                reader.fieldnames = [f.lower().strip() for f in reader.fieldnames]

            imported_count = 0
            skipped_count = 0
            errors = []

            from wtforms.validators import ValidationError

            from changedetectionio.forms import validate_url

            for row_num, row in enumerate(reader, start=2):  # Start at 2 to account for header
                try:
                    url = row.get('url', '').strip()
                    if not url:
                        skipped_count += 1
                        continue

                    # Validate URL
                    try:
                        validate_url(url)
                    except ValidationError:
                        errors.append(f"Row {row_num}: Invalid URL '{url}'")
                        skipped_count += 1
                        continue

                    # Build extras dict for event-specific fields
                    extras = {}

                    # Event name/title
                    event_name = row.get('event_name', '').strip()
                    if event_name:
                        extras['title'] = event_name

                    # Artist
                    artist = row.get('artist', '').strip()
                    if artist:
                        extras['event_artist'] = artist

                    # Venue
                    venue = row.get('venue', '').strip()
                    if venue:
                        extras['event_venue'] = venue

                    # Event date
                    event_date = row.get('event_date', '').strip()
                    if event_date:
                        extras['event_date'] = event_date

                    # Event time
                    event_time = row.get('event_time', '').strip()
                    if event_time:
                        extras['event_time'] = event_time

                    # Set processor to restock_diff for event tracking
                    processor = row.get('processor', 'restock_diff').strip()
                    if processor:
                        extras['processor'] = processor

                    # Tags (comma-separated)
                    tags = row.get('tags', '').strip()

                    # Add the watch
                    new_uuid = datastore.add_watch(
                        url=url,
                        tag=tags,
                        extras=extras,
                        write_to_disk_now=False
                    )

                    if new_uuid:
                        imported_count += 1
                    else:
                        skipped_count += 1

                except Exception as e:
                    logger.error(f"Error importing row {row_num}: {e}")
                    errors.append(f"Row {row_num}: {str(e)}")
                    skipped_count += 1

            # Save to disk after all imports
            datastore.needs_write = True

            # Build result message
            msg = gettext("{} events imported successfully").format(imported_count)
            if skipped_count > 0:
                msg += ", " + gettext("{} skipped").format(skipped_count)
            flash(msg)

            if errors:
                for error in errors[:5]:  # Show first 5 errors
                    flash(error, 'error')
                if len(errors) > 5:
                    flash(gettext("... and {} more errors").format(len(errors) - 5), 'error')

        except Exception as e:
            logger.error(f"CSV import error: {e}")
            flash(gettext('Error reading CSV file: {}').format(str(e)), 'error')

        return redirect(url_for('bulk_operations.bulk_operations_page'))

    @bulk_ops_blueprint.route("/bulk/export/csv", methods=['GET'])
    @login_optionally_required
    def export_events_csv():
        """Export all events (watches) to CSV format.

        Columns: url, tags, event_name, artist, venue, event_date, event_time, processor, last_checked, last_changed
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'url', 'tags', 'event_name', 'artist', 'venue',
            'event_date', 'event_time', 'processor',
            'last_checked', 'last_changed', 'paused'
        ])

        # Get all tag titles for lookup
        tags_data = datastore.data['settings']['application'].get('tags', {})

        # Write each watch
        for uuid, watch in datastore.data['watching'].items():
            # Get tag titles from tag UUIDs
            watch_tags = watch.get('tags', [])
            tag_titles = []
            if isinstance(watch_tags, list):
                for tag_uuid in watch_tags:
                    tag = tags_data.get(tag_uuid)
                    if tag and tag.get('title'):
                        tag_titles.append(tag['title'])

            # Format timestamps
            last_checked = ''
            if watch.get('last_checked'):
                try:
                    last_checked = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watch['last_checked']))
                except (ValueError, OSError):
                    pass

            last_changed = ''
            if watch.get('last_changed'):
                try:
                    last_changed = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watch['last_changed']))
                except (ValueError, OSError):
                    pass

            writer.writerow([
                watch.get('url', ''),
                ', '.join(tag_titles),
                watch.get('title', ''),
                watch.get('event_artist', ''),
                watch.get('event_venue', ''),
                watch.get('event_date', ''),
                watch.get('event_time', ''),
                watch.get('processor', 'text_json_diff'),
                last_checked,
                last_changed,
                'yes' if watch.get('paused') else 'no'
            ])

        # Create response
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=events_export_{int(time.time())}.csv'
            }
        )

    @bulk_ops_blueprint.route("/bulk/export/selected", methods=['POST'])
    @login_optionally_required
    def export_selected_csv():
        """Export selected events to CSV."""
        uuids = [u.strip() for u in request.form.getlist('uuids') if u]

        if not uuids:
            flash(gettext('No events selected for export'), 'error')
            return redirect(url_for('watchlist.index'))

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'url', 'tags', 'event_name', 'artist', 'venue',
            'event_date', 'event_time', 'processor',
            'last_checked', 'last_changed', 'paused'
        ])

        # Get all tag titles for lookup
        tags_data = datastore.data['settings']['application'].get('tags', {})

        # Write selected watches
        for uuid in uuids:
            watch = datastore.data['watching'].get(uuid)
            if not watch:
                continue

            # Get tag titles from tag UUIDs
            watch_tags = watch.get('tags', [])
            tag_titles = []
            if isinstance(watch_tags, list):
                for tag_uuid in watch_tags:
                    tag = tags_data.get(tag_uuid)
                    if tag and tag.get('title'):
                        tag_titles.append(tag['title'])

            # Format timestamps
            last_checked = ''
            if watch.get('last_checked'):
                try:
                    last_checked = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watch['last_checked']))
                except (ValueError, OSError):
                    pass

            last_changed = ''
            if watch.get('last_changed'):
                try:
                    last_changed = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watch['last_changed']))
                except (ValueError, OSError):
                    pass

            writer.writerow([
                watch.get('url', ''),
                ', '.join(tag_titles),
                watch.get('title', ''),
                watch.get('event_artist', ''),
                watch.get('event_venue', ''),
                watch.get('event_date', ''),
                watch.get('event_time', ''),
                watch.get('processor', 'text_json_diff'),
                last_checked,
                last_changed,
                'yes' if watch.get('paused') else 'no'
            ])

        # Create response
        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=events_export_{int(time.time())}.csv'
            }
        )

    @bulk_ops_blueprint.route("/bulk/progress/<operation_id>", methods=['GET'])
    @login_optionally_required
    def get_progress(operation_id):
        """Get progress of a bulk operation."""
        progress = _progress_tracker.get(operation_id, {
            'status': 'unknown',
            'processed': 0,
            'total': 0,
            'message': ''
        })
        return jsonify(progress)

    @bulk_ops_blueprint.route("/bulk/template/csv", methods=['GET'])
    @login_optionally_required
    def download_csv_template():
        """Download a CSV template for importing events."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header with expected columns
        writer.writerow([
            'url', 'tags', 'event_name', 'artist', 'venue',
            'event_date', 'event_time', 'processor'
        ])

        # Write example row
        writer.writerow([
            'https://example.com/event/123',
            'concerts, rock',
            'Summer Festival 2024',
            'The Band',
            'Madison Square Garden',
            '2024-07-15',
            '19:00',
            'restock_diff'
        ])

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': 'attachment; filename=events_import_template.csv'
            }
        )

    return bulk_ops_blueprint
