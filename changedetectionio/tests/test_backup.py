#!/usr/bin/env python3

from .util import set_original_response, live_server_setup, wait_for_all_checks
from flask import url_for
import io
from zipfile import ZipFile
import re
import time
from changedetectionio.model import Watch, Tag


def test_backup(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)


    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)+"?somechar=őőőőőőőő"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Launch the thread in the background to create the backup
    res = client.get(
        url_for("backups.request_backup"),
        follow_redirects=True
    )
    time.sleep(4)

    res = client.get(
        url_for("backups.create"),
        follow_redirects=True
    )
    # Can see the download link to the backup
    assert b'<a href="/backups/download/changedetection-backup-20' in res.data
    assert b'Remove backups' in res.data

    # Get the latest one
    res = client.get(
        url_for("backups.download_backup", filename="latest"),
        follow_redirects=True
    )

    # Should get the right zip content type
    assert res.content_type == "application/zip"

    # Should be PK/ZIP stream
    assert res.data.count(b'PK') >= 2

    backup = ZipFile(io.BytesIO(res.data))
    l = backup.namelist()

    # Check for UUID-based txt files (history, snapshot, and last-checksum)
    uuid4hex_txt = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}.*txt', re.I)
    txt_files = list(filter(uuid4hex_txt.match, l))
    # Should be three txt files in the archive (history, snapshot, and last-checksum)
    assert len(txt_files) == 3

    # Check for watch.json files (new format)
    uuid4hex_json = re.compile('^[a-f0-9]{8}-?[a-f0-9]{4}-?4[a-f0-9]{3}-?[89ab][a-f0-9]{3}-?[a-f0-9]{12}/watch\.json$', re.I)
    json_files = list(filter(uuid4hex_json.match, l))
    # Should be one watch.json file in the archive (the imported watch)
    assert len(json_files) == 1, f"Expected 1 watch.json file, found {len(json_files)}: {json_files}"

    # Check for changedetection.json (settings file)
    assert 'changedetection.json' in l, "changedetection.json should be in backup"

    # Get the latest one
    res = client.get(
        url_for("backups.remove_backups"),
        follow_redirects=True
    )

    assert b'No backups found.' in res.data


def test_watch_data_package_download(client, live_server, measure_memory_usage, datastore_path):
    """Test downloading a single watch's data as a zip package"""

    set_original_response(datastore_path=datastore_path)

    uuid = client.application.config.get('DATASTORE').add_watch(url=url_for('test_endpoint', _external=True))
    tag_uuid = client.application.config.get('DATASTORE').add_tag(title="Tasty backup tag")
    tag_uuid2 = client.application.config.get('DATASTORE').add_tag(title="Tasty backup tag number two")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # Download the watch data package
    res = client.get(url_for("ui.ui_edit.watch_get_data_package", uuid=uuid))

    # Should get the right zip content type
    assert res.content_type == "application/zip"

    # Should be PK/ZIP stream (PKzip header)
    assert res.data[:2] == b'PK', "File should start with PK (PKzip header)"
    assert res.data.count(b'PK') >= 2, "Should have multiple PK markers (zip file structure)"

    # Verify zip contents
    backup = ZipFile(io.BytesIO(res.data))
    files = backup.namelist()

    # Should have files in a UUID directory
    assert any(uuid in f for f in files), f"Files should be in UUID directory: {files}"

    # Should contain watch.json
    watch_json_path = f"{uuid}/watch.json"
    assert watch_json_path in files, f"Should contain watch.json, got: {files}"

    # Should contain history/snapshot files
    uuid4hex_txt = re.compile(f'^{re.escape(uuid)}/.*\\.txt', re.I)
    txt_files = list(filter(uuid4hex_txt.match, files))
    assert len(txt_files) > 0, f"Should have at least one .txt file (history/snapshot), got: {files}"


def test_backup_restore(client, live_server, measure_memory_usage, datastore_path):
    """Test that a full backup zip can be restored — watches and tags survive a round-trip."""

    set_original_response(datastore_path=datastore_path)

    datastore = live_server.app.config['DATASTORE']
    watch_url = url_for('test_endpoint', _external=True)

    # Set up: one watch and two tags
    uuid = datastore.add_watch(url=watch_url)
    tag_uuid = datastore.add_tag(title="Tasty backup tag")
    tag_uuid2 = datastore.add_tag(title="Tasty backup tag number two")

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Create a full backup
    client.get(url_for("backups.request_backup"), follow_redirects=True)
    time.sleep(4)

    # Download the latest backup zip
    res = client.get(url_for("backups.download_backup", filename="latest"), follow_redirects=True)
    assert res.content_type == "application/zip"
    zip_data = res.data

    # Confirm the zip contains both watch.json and tag.json entries
    backup = ZipFile(io.BytesIO(zip_data))
    names = backup.namelist()
    assert f"{uuid}/watch.json" in names, f"watch.json missing from backup: {names}"
    assert f"{tag_uuid}/tag.json" in names, f"tag.json for tag 1 missing from backup: {names}"
    assert f"{tag_uuid2}/tag.json" in names, f"tag.json for tag 2 missing from backup: {names}"

    # --- Wipe everything ---
    datastore.delete('all')
    client.get(url_for("tags.delete_all"), follow_redirects=True)

    assert uuid not in datastore.data['watching'], "Watch should be gone after delete"
    assert tag_uuid not in datastore.data['settings']['application']['tags'], "Tag 1 should be gone after delete"
    assert tag_uuid2 not in datastore.data['settings']['application']['tags'], "Tag 2 should be gone after delete"

    # --- Restore from the backup zip ---
    res = client.post(
        url_for("backups.restore.backups_restore_start"),
        data={
            'zip_file': (io.BytesIO(zip_data), 'backup.zip'),
            'include_groups': 'y',
            'include_groups_replace_existing': 'y',
            'include_watches': 'y',
            'include_watches_replace_existing': 'y',
        },
        content_type='multipart/form-data',
        follow_redirects=True
    )
    assert res.status_code == 200

    # Wait for the thread to finish
    time.sleep(2)

    # --- Watch checks ---
    restored_watch = datastore.data['watching'].get(uuid)
    assert restored_watch is not None, f"Watch {uuid} not found after restore"
    assert restored_watch['url'] == watch_url, "Restored watch URL does not match"
    assert isinstance(restored_watch, Watch.model), \
        f"Watch not properly rehydrated, got {type(restored_watch)}"
    assert restored_watch.history_n >= 1, \
        f"Restored watch should have at least 1 history entry, got {restored_watch.history_n}"

    # --- Tag checks ---
    restored_tags = datastore.data['settings']['application']['tags']

    restored_tag = restored_tags.get(tag_uuid)
    assert restored_tag is not None, f"Tag {tag_uuid} not found after restore"
    assert restored_tag['title'] == "Tasty backup tag", "Restored tag 1 title does not match"
    assert isinstance(restored_tag, Tag.model), \
        f"Tag 1 not properly rehydrated, got {type(restored_tag)}"

    restored_tag2 = restored_tags.get(tag_uuid2)
    assert restored_tag2 is not None, f"Tag {tag_uuid2} not found after restore"
    assert restored_tag2['title'] == "Tasty backup tag number two", "Restored tag 2 title does not match"
    assert isinstance(restored_tag2, Tag.model), \
        f"Tag 2 not properly rehydrated, got {type(restored_tag2)}"