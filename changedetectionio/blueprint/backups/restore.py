import io
import json
import os
import re
import shutil
import tempfile
import threading
import zipfile

from flask import Blueprint, render_template, flash, url_for, redirect, request
from flask_babel import gettext, lazy_gettext as _l
from wtforms import Form, BooleanField, SubmitField
from flask_wtf.file import FileField, FileAllowed
from loguru import logger

from changedetectionio.flask_app import login_optionally_required

# Maximum size of the uploaded zip file. Override via env var MAX_RESTORE_UPLOAD_MB.
_MAX_UPLOAD_BYTES = int(os.getenv("MAX_RESTORE_UPLOAD_MB", 256)) * 1024 * 1024
# Maximum total uncompressed size of all entries (zip-bomb guard). Override via MAX_RESTORE_DECOMPRESSED_MB.
_MAX_DECOMPRESSED_BYTES = int(os.getenv("MAX_RESTORE_DECOMPRESSED_MB", 1024)) * 1024 * 1024
# Only top-level directories whose name is a valid UUID are treated as watch/tag entries.
_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
    re.IGNORECASE,
)


class RestoreForm(Form):
    zip_file = FileField(_l('Backup zip file'), validators=[
        FileAllowed(['zip'], _l('Must be a .zip backup file!'))
    ])
    include_groups = BooleanField(_l('Include groups'), default=True)
    include_groups_replace_existing = BooleanField(_l('Replace existing groups of the same UUID'), default=True)
    include_watches = BooleanField(_l('Include watches'), default=True)
    include_watches_replace_existing = BooleanField(_l('Replace existing watches of the same UUID'), default=True)
    submit = SubmitField(_l('Restore backup'))


def import_from_zip(zip_stream, datastore, include_groups, include_groups_replace, include_watches, include_watches_replace):
    """
    Extract and import watches and groups from a backup zip stream.

    Mirrors the store's _load_watches / _load_tags loading pattern:
      - UUID dirs with tag.json  → Tag.model + tag_obj.commit()
      - UUID dirs with watch.json → rehydrate_entity + watch_obj.commit()

    Returns a dict with counts: restored_groups, skipped_groups, restored_watches, skipped_watches.
    Raises zipfile.BadZipFile if the stream is not a valid zip.
    """
    from changedetectionio.model import Tag

    restored_groups = 0
    skipped_groups = 0
    restored_watches = 0
    skipped_watches = 0

    current_tags = datastore.data['settings']['application'].get('tags', {})
    current_watches = datastore.data['watching']

    with tempfile.TemporaryDirectory() as tmpdir:
        logger.debug(f"Restore: extracting zip to {tmpdir}")
        with zipfile.ZipFile(zip_stream, 'r') as zf:
            total_uncompressed = sum(m.file_size for m in zf.infolist())
            if total_uncompressed > _MAX_DECOMPRESSED_BYTES:
                raise ValueError(
                    f"Backup archive decompressed size ({total_uncompressed // (1024 * 1024)} MB) "
                    f"exceeds the {_MAX_DECOMPRESSED_BYTES // (1024 * 1024)} MB limit"
                )
            resolved_dest = os.path.realpath(tmpdir)
            for member in zf.infolist():
                member_dest = os.path.realpath(os.path.join(resolved_dest, member.filename))
                if not member_dest.startswith(resolved_dest + os.sep) and member_dest != resolved_dest:
                    raise ValueError(f"Zip Slip path traversal detected in backup archive: {member.filename!r}")
                zf.extract(member, tmpdir)
        logger.debug("Restore: zip extracted, scanning UUID directories")

        for entry in os.scandir(tmpdir):
            if not entry.is_dir():
                continue

            uuid = entry.name
            if not _UUID_RE.match(uuid):
                logger.warning(f"Restore: skipping non-UUID directory {uuid!r}")
                continue
            tag_json_path = os.path.join(entry.path, 'tag.json')
            watch_json_path = os.path.join(entry.path, 'watch.json')

            # --- Tags (groups) ---
            if include_groups and os.path.exists(tag_json_path):
                if uuid in current_tags and not include_groups_replace:
                    logger.debug(f"Restore: skipping existing group {uuid} (replace not requested)")
                    skipped_groups += 1
                    continue

                try:
                    with open(tag_json_path, 'r', encoding='utf-8') as f:
                        tag_data = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Restore: failed to read tag.json for {uuid}: {e}")
                    continue

                title = tag_data.get('title', uuid)
                logger.debug(f"Restore: importing group '{title}' ({uuid})")

                # Mirror _load_tags: set uuid and force processor
                tag_data['uuid'] = uuid
                tag_data['processor'] = 'restock_diff'

                # Copy the UUID directory so data_dir exists for commit()
                dst_dir = os.path.join(datastore.datastore_path, uuid)
                if os.path.exists(dst_dir):
                    shutil.rmtree(dst_dir)
                shutil.copytree(entry.path, dst_dir)

                tag_obj = Tag.model(
                    datastore_path=datastore.datastore_path,
                    __datastore=datastore.data,
                    default=tag_data
                )
                current_tags[uuid] = tag_obj
                tag_obj.commit()
                restored_groups += 1
                logger.success(f"Restore: group '{title}' ({uuid}) restored")

            # --- Watches ---
            elif include_watches and os.path.exists(watch_json_path):
                if uuid in current_watches and not include_watches_replace:
                    logger.debug(f"Restore: skipping existing watch {uuid} (replace not requested)")
                    skipped_watches += 1
                    continue

                try:
                    with open(watch_json_path, 'r', encoding='utf-8') as f:
                        watch_data = json.load(f)
                except (json.JSONDecodeError, IOError) as e:
                    logger.error(f"Restore: failed to read watch.json for {uuid}: {e}")
                    continue

                url = watch_data.get('url', uuid)
                logger.debug(f"Restore: importing watch '{url}' ({uuid})")

                # Copy UUID directory first so data_dir and history files exist
                dst_dir = os.path.join(datastore.datastore_path, uuid)
                if os.path.exists(dst_dir):
                    shutil.rmtree(dst_dir)
                shutil.copytree(entry.path, dst_dir)

                # Mirror _load_watches / rehydrate_entity
                watch_data['uuid'] = uuid
                watch_obj = datastore.rehydrate_entity(uuid, watch_data)
                current_watches[uuid] = watch_obj
                watch_obj.commit()
                restored_watches += 1
                logger.success(f"Restore: watch '{url}' ({uuid}) restored")

        logger.debug(f"Restore: scan complete - groups {restored_groups} restored / {skipped_groups} skipped, "
                     f"watches {restored_watches} restored / {skipped_watches} skipped")

    # Persist changedetection.json (includes the updated tags dict)
    logger.debug("Restore: committing datastore settings")
    datastore.commit()

    return {
        'restored_groups': restored_groups,
        'skipped_groups': skipped_groups,
        'restored_watches': restored_watches,
        'skipped_watches': skipped_watches,
    }



def construct_restore_blueprint(datastore):
    restore_blueprint = Blueprint('restore', __name__, template_folder="templates")
    restore_threads = []

    @login_optionally_required
    @restore_blueprint.route("/restore", methods=['GET'])
    def restore():
        form = RestoreForm()
        return render_template("backup_restore.html",
                               form=form,
                               restore_running=any(t.is_alive() for t in restore_threads),
                               max_upload_mb=_MAX_UPLOAD_BYTES // (1024 * 1024),
                               max_decompressed_mb=_MAX_DECOMPRESSED_BYTES // (1024 * 1024))

    @login_optionally_required
    @restore_blueprint.route("/restore/start", methods=['POST'])
    def backups_restore_start():
        if any(t.is_alive() for t in restore_threads):
            flash(gettext("A restore is already running, check back in a few minutes"), "error")
            return redirect(url_for('backups.restore.restore'))

        zip_file = request.files.get('zip_file')
        if not zip_file or not zip_file.filename:
            flash(gettext("No file uploaded"), "error")
            return redirect(url_for('backups.restore.restore'))

        if not zip_file.filename.lower().endswith('.zip'):
            flash(gettext("File must be a .zip backup file"), "error")
            return redirect(url_for('backups.restore.restore'))

        # Reject oversized uploads before reading the stream into memory.
        content_length = request.content_length
        if content_length and content_length > _MAX_UPLOAD_BYTES:
            flash(gettext("Backup file is too large (max %(mb)s MB)", mb=_MAX_UPLOAD_BYTES // (1024 * 1024)), "error")
            return redirect(url_for('backups.restore.restore'))

        # Read into memory now — the request stream is gone once we return.
        # Read one byte beyond the limit so we can detect truncated-but-still-oversized streams.
        try:
            raw = zip_file.read(_MAX_UPLOAD_BYTES + 1)
            if len(raw) > _MAX_UPLOAD_BYTES:
                flash(gettext("Backup file is too large (max %(mb)s MB)", mb=_MAX_UPLOAD_BYTES // (1024 * 1024)), "error")
                return redirect(url_for('backups.restore.restore'))
            zip_bytes = io.BytesIO(raw)
            with zipfile.ZipFile(zip_bytes):  # quick validity check before spawning
                pass
            zip_bytes.seek(0)
        except zipfile.BadZipFile:
            flash(gettext("Invalid or corrupted zip file"), "error")
            return redirect(url_for('backups.restore.restore'))

        include_groups = request.form.get('include_groups') == 'y'
        include_groups_replace = request.form.get('include_groups_replace_existing') == 'y'
        include_watches = request.form.get('include_watches') == 'y'
        include_watches_replace = request.form.get('include_watches_replace_existing') == 'y'

        restore_thread = threading.Thread(
            target=import_from_zip,
            kwargs={
                'zip_stream': zip_bytes,
                'datastore': datastore,
                'include_groups': include_groups,
                'include_groups_replace': include_groups_replace,
                'include_watches': include_watches,
                'include_watches_replace': include_watches_replace,
            },
            daemon=True,
            name="BackupRestore"
        )
        restore_thread.start()
        restore_threads[:] = [t for t in restore_threads if t.is_alive()]
        restore_threads.append(restore_thread)
        flash(gettext("Restore started in background, check back in a few minutes."))
        return redirect(url_for('backups.restore.restore'))

    return restore_blueprint
