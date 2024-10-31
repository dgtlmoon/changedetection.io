import datetime
import glob
import threading

from flask import Blueprint, render_template, send_from_directory, flash, url_for, redirect, abort
import os

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required
from loguru import logger

BACKUP_FILENAME_FORMAT = "changedetection-backup-{}.zip"


def create_backup(datastore_path, watches: dict):
    logger.debug("Creating backup...")
    import zipfile
    from pathlib import Path

    # create a ZipFile object
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    backupname = BACKUP_FILENAME_FORMAT.format(timestamp)
    backup_filepath = os.path.join(datastore_path, backupname)

    with zipfile.ZipFile(backup_filepath.replace('.zip', '.tmp'), "w",
                         compression=zipfile.ZIP_DEFLATED,
                         compresslevel=8) as zipObj:

        # Add the index
        zipObj.write(os.path.join(datastore_path, "url-watches.json"), arcname="url-watches.json")

        # Add the flask app secret
        zipObj.write(os.path.join(datastore_path, "secret.txt"), arcname="secret.txt")

        # Add any data in the watch data directory.
        for uuid, w in watches.items():
            for f in Path(w.watch_data_dir).glob('*'):
                zipObj.write(f,
                             # Use the full path to access the file, but make the file 'relative' in the Zip.
                             arcname=os.path.join(f.parts[-2], f.parts[-1]),
                             compress_type=zipfile.ZIP_DEFLATED,
                             compresslevel=8)

        # Create a list file with just the URLs, so it's easier to port somewhere else in the future
        list_file = "url-list.txt"
        with open(os.path.join(datastore_path, list_file), "w") as f:
            for uuid in watches:
                url = watches[uuid]["url"]
                f.write("{}\r\n".format(url))
        list_with_tags_file = "url-list-with-tags.txt"
        with open(
                os.path.join(datastore_path, list_with_tags_file), "w"
        ) as f:
            for uuid in watches:
                url = watches[uuid].get('url')
                tag = watches[uuid].get('tags', {})
                f.write("{} {}\r\n".format(url, tag))

        # Add it to the Zip
        zipObj.write(
            os.path.join(datastore_path, list_file),
            arcname=list_file,
            compress_type=zipfile.ZIP_DEFLATED,
            compresslevel=8,
        )
        zipObj.write(
            os.path.join(datastore_path, list_with_tags_file),
            arcname=list_with_tags_file,
            compress_type=zipfile.ZIP_DEFLATED,
            compresslevel=8,
        )

    # Now it's done, rename it so it shows up finally and its completed being written.
    os.rename(backup_filepath.replace('.zip', '.tmp'), backup_filepath.replace('.tmp', '.zip'))


def construct_blueprint(datastore: ChangeDetectionStore):
    backups_blueprint = Blueprint('backups', __name__, template_folder="templates")
    backup_threads = []

    @login_optionally_required
    @backups_blueprint.route("/request-backup", methods=['GET'])
    def request_backup():
        if any(thread.is_alive() for thread in backup_threads):
            flash("A backup is already running, check back in a few minutes", "error")
            return redirect(url_for('backups.index'))

        if len(find_backups()) > int(os.getenv("MAX_NUMBER_BACKUPS", 100)):
            flash("Maximum number of backups reached, please remove some", "error")
            return redirect(url_for('backups.index'))

        # Be sure we're written fresh
        datastore.sync_to_json()
        zip_thread = threading.Thread(target=create_backup, args=(datastore.datastore_path, datastore.data.get("watching")))
        zip_thread.start()
        backup_threads.append(zip_thread)
        flash("Backup building in background, check back in a few minutes.")

        return redirect(url_for('backups.index'))

    def find_backups():
        backup_filepath = os.path.join(datastore.datastore_path, BACKUP_FILENAME_FORMAT.format("*"))
        backups = glob.glob(backup_filepath)
        backup_info = []

        for backup in backups:
            size = os.path.getsize(backup) / (1024 * 1024)
            creation_time = os.path.getctime(backup)
            backup_info.append({
                'filename': os.path.basename(backup),
                'filesize': f"{size:.2f}",
                'creation_time': creation_time
            })

        backup_info.sort(key=lambda x: x['creation_time'], reverse=True)

        return backup_info

    @login_optionally_required
    @backups_blueprint.route("/download/<string:filename>", methods=['GET'])
    def download_backup(filename):
        import re
        filename = filename.strip()
        backup_filename_regex = BACKUP_FILENAME_FORMAT.format("\d+")

        full_path = os.path.join(os.path.abspath(datastore.datastore_path), filename)
        if not full_path.startswith(os.path.abspath(datastore.datastore_path)):
            abort(404)

        if filename == 'latest':
            backups = find_backups()
            filename = backups[0]['filename']

        if not re.match(r"^" + backup_filename_regex + "$", filename):
            abort(400)  # Bad Request if the filename doesn't match the pattern

        logger.debug(f"Backup download request for '{full_path}'")
        return send_from_directory(os.path.abspath(datastore.datastore_path), filename, as_attachment=True)

    @login_optionally_required
    @backups_blueprint.route("/", methods=['GET'])
    def index():
        backups = find_backups()
        output = render_template("overview.html",
                                 available_backups=backups,
                                 backup_running=any(thread.is_alive() for thread in backup_threads)
                                 )

        return output

    @login_optionally_required
    @backups_blueprint.route("/remove-backups", methods=['GET'])
    def remove_backups():

        backup_filepath = os.path.join(datastore.datastore_path, BACKUP_FILENAME_FORMAT.format("*"))
        backups = glob.glob(backup_filepath)
        for backup in backups:
            os.unlink(backup)

        flash("Backups were deleted.")

        return redirect(url_for('backups.index'))

    return backups_blueprint
