"""
Schema update migrations for the datastore.

This module contains all schema version upgrade methods (update_1 through update_N).
These are mixed into ChangeDetectionStore to keep the main store file focused.

IMPORTANT: Each update could be run even when they have a new install and the schema is correct.
Therefore - each `update_n` should be very careful about checking if it needs to actually run.
"""

import os
import re
import shutil
import tarfile
import time
from loguru import logger
from copy import deepcopy

from ..html_tools import TRANSLATE_WHITESPACE_TABLE
from ..processors.restock_diff import Restock
from ..blueprint.rss import RSS_CONTENT_FORMAT_DEFAULT
from ..model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
from .file_saving_datastore import save_watch_atomic


def create_backup_tarball(datastore_path, update_number):
    """
    Create a tarball backup of the entire datastore structure before running an update.

    Includes:
    - All {uuid}/watch.json files
    - All {uuid}/tag.json files
    - changedetection.json (settings, if it exists)
    - url-watches.json (legacy format, if it exists)
    - Directory structure preserved

    Args:
        datastore_path: Path to datastore directory
        update_number: Update number being applied

    Returns:
        str: Path to created tarball, or None if backup failed

    Restoration:
    To restore from a backup:
        cd /path/to/datastore
        tar -xzf before-update-N-timestamp.tar.gz
    This will restore all watch.json and tag.json files and settings to their pre-update state.
    """
    timestamp = int(time.time())
    backup_filename = f"before-update-{update_number}-{timestamp}.tar.gz"
    backup_path = os.path.join(datastore_path, backup_filename)

    try:
        logger.info(f"Creating backup tarball: {backup_filename}")

        with tarfile.open(backup_path, "w:gz") as tar:
            # Backup changedetection.json if it exists (new format)
            changedetection_json = os.path.join(datastore_path, "changedetection.json")
            if os.path.isfile(changedetection_json):
                tar.add(changedetection_json, arcname="changedetection.json")
                logger.debug("Added changedetection.json to backup")

            # Backup url-watches.json if it exists (legacy format)
            url_watches_json = os.path.join(datastore_path, "url-watches.json")
            if os.path.isfile(url_watches_json):
                tar.add(url_watches_json, arcname="url-watches.json")
                logger.debug("Added url-watches.json to backup")

            # Backup all watch/tag directories with their JSON files
            # This preserves the UUID directory structure
            watch_count = 0
            tag_count = 0
            for entry in os.listdir(datastore_path):
                entry_path = os.path.join(datastore_path, entry)

                # Skip if not a directory
                if not os.path.isdir(entry_path):
                    continue

                # Skip hidden directories and backup directories
                if entry.startswith('.') or entry.startswith('before-update-'):
                    continue

                # Backup watch.json if exists
                watch_json = os.path.join(entry_path, "watch.json")
                if os.path.isfile(watch_json):
                    tar.add(watch_json, arcname=f"{entry}/watch.json")
                    watch_count += 1

                    if watch_count % 100 == 0:
                        logger.debug(f"Backed up {watch_count} watch.json files...")

                # Backup tag.json if exists
                tag_json = os.path.join(entry_path, "tag.json")
                if os.path.isfile(tag_json):
                    tar.add(tag_json, arcname=f"{entry}/tag.json")
                    tag_count += 1

            logger.success(f"Backup created: {backup_filename} ({watch_count} watches, {tag_count} tags)")
            return backup_path

    except Exception as e:
        logger.error(f"Failed to create backup tarball: {e}")
        # Try to clean up partial backup
        if os.path.exists(backup_path):
            try:
                os.unlink(backup_path)
            except:
                pass
        return None


class DatastoreUpdatesMixin:
    """
    Mixin class containing all schema update methods.

    This class is inherited by ChangeDetectionStore to provide schema migration functionality.
    Each update_N method upgrades the schema from version N-1 to version N.
    """

    def get_updates_available(self):
        """
        Discover all available update methods.

        Returns:
            list: Sorted list of update version numbers (e.g., [1, 2, 3, ..., 26])
        """
        import inspect
        updates_available = []
        for i, o in inspect.getmembers(self, predicate=inspect.ismethod):
            m = re.search(r'update_(\d+)$', i)
            if m:
                updates_available.append(int(m.group(1)))
        updates_available.sort()

        return updates_available

    def run_updates(self, current_schema_version=None):
        """
        Run all pending schema updates sequentially.

        Args:
            current_schema_version: Optional current schema version. If provided, only run updates
                                   greater than this version. If None, uses the schema version from
                                   the datastore. If no schema version exists in datastore and it appears
                                   to be a fresh install, sets to latest update number (no updates needed).

        IMPORTANT: Each update could be run even when they have a new install and the schema is correct.
        Therefore - each `update_n` should be very careful about checking if it needs to actually run.

        Process:
        1. Get list of available updates
        2. For each update > current schema version:
           - Create backup of datastore
           - Run update method
           - Update schema version and commit settings
           - Commit all watches and tags
        3. If any update fails, stop processing
        4. All changes saved via individual .commit() calls
        """
        updates_available = self.get_updates_available()

        # Determine current schema version
        if current_schema_version is None:
            # Check if schema_version exists in datastore
            current_schema_version = self.data['settings']['application'].get('schema_version')

            if current_schema_version is None:
                # No schema version found - could be a fresh install or very old datastore
                # If this is a fresh/new config with no watches, assume it's up-to-date
                # and set to latest update number (no updates needed)
                if len(self.data['watching']) == 0:
                    # Get the highest update number from available update methods
                    latest_update = updates_available[-1] if updates_available else 0
                    logger.info(f"No schema version found and no watches exist - assuming fresh install, setting schema_version to {latest_update}")
                    self.data['settings']['application']['schema_version'] = latest_update
                    self.commit()
                    return  # No updates needed for fresh install
                else:
                    # Has watches but no schema version - likely old datastore, run all updates
                    logger.warning("No schema version found but watches exist - running all updates from version 0")
                    current_schema_version = 0

        logger.info(f"Current schema version: {current_schema_version}")

        updates_ran = []

        for update_n in updates_available:
            if update_n > current_schema_version:
                logger.critical(f"Applying update_{update_n}")

                # Create tarball backup of entire datastore structure
                # This includes all watch.json files, settings, and preserves directory structure
                backup_path = create_backup_tarball(self.datastore_path, update_n)
                if backup_path:
                    logger.info(f"Backup created at: {backup_path}")
                else:
                    logger.warning("Backup creation failed, but continuing with update")

                try:
                    update_method = getattr(self, f"update_{update_n}")()
                except Exception as e:
                    logger.error(f"Error while trying update_{update_n}")
                    logger.error(e)
                    # Don't run any more updates
                    return
                else:
                    # Bump the version
                    self.data['settings']['application']['schema_version'] = update_n
                    self.commit()

                    logger.success(f"Update {update_n} completed")

                    # Track which updates ran
                    updates_ran.append(update_n)

    # ============================================================================
    # Individual Update Methods
    # ============================================================================

    def update_1(self):
        """Convert minutes to seconds on settings and each watch."""
        if self.data['settings']['requests'].get('minutes_between_check'):
            self.data['settings']['requests']['time_between_check']['minutes'] = self.data['settings']['requests']['minutes_between_check']
            # Remove the default 'hours' that is set from the model
            self.data['settings']['requests']['time_between_check']['hours'] = None

        for uuid, watch in self.data['watching'].items():
            if 'minutes_between_check' in watch:
                # Only upgrade individual watch time if it was set
                if watch.get('minutes_between_check', False):
                    self.data['watching'][uuid]['time_between_check']['minutes'] = watch['minutes_between_check']

    def update_2(self):
        """
        Move the history list to a flat text file index.
        Better than SQLite because this list is only appended to, and works across NAS / NFS type setups.
        """
        # @todo test running this on a newly updated one (when this already ran)
        for uuid, watch in self.data['watching'].items():
            history = []

            if watch.get('history', False):
                for d, p in watch['history'].items():
                    d = int(d)  # Used to be keyed as str, we'll fix this now too
                    history.append("{},{}\n".format(d, p))

                if len(history):
                    target_path = os.path.join(self.datastore_path, uuid)
                    if os.path.exists(target_path):
                        with open(os.path.join(target_path, "history.txt"), "w") as f:
                            f.writelines(history)
                    else:
                        logger.warning(f"Datastore history directory {target_path} does not exist, skipping history import.")

                # No longer needed, dynamically pulled from the disk when needed.
                # But we should set it back to a empty dict so we don't break if this schema runs on an earlier version.
                # In the distant future we can remove this entirely
                self.data['watching'][uuid]['history'] = {}

    def update_3(self):
        """We incorrectly stored last_changed when there was not a change, and then confused the output list table."""
        # see https://github.com/dgtlmoon/changedetection.io/pull/835
        return

    def update_4(self):
        """`last_changed` not needed, we pull that information from the history.txt index."""
        for uuid, watch in self.data['watching'].items():
            try:
                # Remove it from the struct
                del(watch['last_changed'])
            except:
                continue
        return

    def update_5(self):
        """
        If the watch notification body, title look the same as the global one, unset it, so the watch defaults back to using the main settings.
        In other words - the watch notification_title and notification_body are not needed if they are the same as the default one.
        """
        current_system_body = self.data['settings']['application']['notification_body'].translate(TRANSLATE_WHITESPACE_TABLE)
        current_system_title = self.data['settings']['application']['notification_body'].translate(TRANSLATE_WHITESPACE_TABLE)
        for uuid, watch in self.data['watching'].items():
            try:
                watch_body = watch.get('notification_body', '')
                if watch_body and watch_body.translate(TRANSLATE_WHITESPACE_TABLE) == current_system_body:
                    # Looks the same as the default one, so unset it
                    watch['notification_body'] = None

                watch_title = watch.get('notification_title', '')
                if watch_title and watch_title.translate(TRANSLATE_WHITESPACE_TABLE) == current_system_title:
                    # Looks the same as the default one, so unset it
                    watch['notification_title'] = None
            except Exception as e:
                continue
        return

    def update_7(self):
        """
        We incorrectly used common header overrides that should only apply to Requests.
        These are now handled in content_fetcher::html_requests and shouldnt be passed to Playwright/Selenium.
        """
        # These were hard-coded in early versions
        for v in ['User-Agent', 'Accept', 'Accept-Encoding', 'Accept-Language']:
            if self.data['settings']['headers'].get(v):
                del self.data['settings']['headers'][v]

    def update_8(self):
        """Convert filters to a list of filters css_filter -> include_filters."""
        for uuid, watch in self.data['watching'].items():
            try:
                existing_filter = watch.get('css_filter', '')
                if existing_filter:
                    watch['include_filters'] = [existing_filter]
            except:
                continue
        return

    def update_9(self):
        """Convert old static notification tokens to jinja2 tokens."""
        # Each watch
        # only { } not {{ or }}
        r = r'(?<!{){(?!{)(\w+)(?<!})}(?!})'
        for uuid, watch in self.data['watching'].items():
            try:
                n_body = watch.get('notification_body', '')
                if n_body:
                    watch['notification_body'] = re.sub(r, r'{{\1}}', n_body)

                n_title = watch.get('notification_title')
                if n_title:
                    watch['notification_title'] = re.sub(r, r'{{\1}}', n_title)

                n_urls = watch.get('notification_urls')
                if n_urls:
                    for i, url in enumerate(n_urls):
                        watch['notification_urls'][i] = re.sub(r, r'{{\1}}', url)

            except:
                continue

        # System wide
        n_body = self.data['settings']['application'].get('notification_body')
        if n_body:
            self.data['settings']['application']['notification_body'] = re.sub(r, r'{{\1}}', n_body)

        n_title = self.data['settings']['application'].get('notification_title')
        if n_body:
            self.data['settings']['application']['notification_title'] = re.sub(r, r'{{\1}}', n_title)

        n_urls = self.data['settings']['application'].get('notification_urls')
        if n_urls:
            for i, url in enumerate(n_urls):
                self.data['settings']['application']['notification_urls'][i] = re.sub(r, r'{{\1}}', url)

        return

    def update_10(self):
        """Some setups may have missed the correct default, so it shows the wrong config in the UI, although it will default to system-wide."""
        for uuid, watch in self.data['watching'].items():
            try:
                if not watch.get('fetch_backend', ''):
                    watch['fetch_backend'] = 'system'
            except:
                continue
        return

    def update_12(self):
        """Create tag objects and their references from existing tag text."""
        i = 0
        for uuid, watch in self.data['watching'].items():
            # Split out and convert old tag string
            tag = watch.get('tag')
            if tag:
                tag_uuids = []
                for t in tag.split(','):
                    tag_uuids.append(self.add_tag(title=t))

                self.data['watching'][uuid]['tags'] = tag_uuids

    def update_13(self):
        """#1775 - Update 11 did not update the records correctly when adding 'date_created' values for sorting."""
        i = 0
        for uuid, watch in self.data['watching'].items():
            if not watch.get('date_created'):
                self.data['watching'][uuid]['date_created'] = i
            i += 1
        return

    def update_14(self):
        """#1774 - protect xpath1 against migration."""
        for awatch in self.data["watching"]:
            if self.data["watching"][awatch]['include_filters']:
                for num, selector in enumerate(self.data["watching"][awatch]['include_filters']):
                    if selector.startswith('/'):
                        self.data["watching"][awatch]['include_filters'][num] = 'xpath1:' + selector
                    if selector.startswith('xpath:'):
                        self.data["watching"][awatch]['include_filters'][num] = selector.replace('xpath:', 'xpath1:', 1)

    def update_15(self):
        """Use more obvious default time setting."""
        for uuid in self.data["watching"]:
            if self.data["watching"][uuid]['time_between_check'] == self.data['settings']['requests']['time_between_check']:
                # What the old logic was, which was pretty confusing
                self.data["watching"][uuid]['time_between_check_use_default'] = True
            elif all(value is None or value == 0 for value in self.data["watching"][uuid]['time_between_check'].values()):
                self.data["watching"][uuid]['time_between_check_use_default'] = True
            else:
                # Something custom here
                self.data["watching"][uuid]['time_between_check_use_default'] = False

    def update_16(self):
        """Correctly set datatype for older installs where 'tag' was string and update_12 did not catch it."""
        for uuid, watch in self.data['watching'].items():
            if isinstance(watch.get('tags'), str):
                self.data['watching'][uuid]['tags'] = []

    def update_17(self):
        """Migrate old 'in_stock' values to the new Restock."""
        for uuid, watch in self.data['watching'].items():
            if 'in_stock' in watch:
                watch['restock'] = Restock({'in_stock': watch.get('in_stock')})
                del watch['in_stock']

    def update_18(self):
        """Migrate old restock settings."""
        for uuid, watch in self.data['watching'].items():
            if not watch.get('restock_settings'):
                # So we enable price following by default
                self.data['watching'][uuid]['restock_settings'] = {'follow_price_changes': True}

            # Migrate and cleanoff old value
            self.data['watching'][uuid]['restock_settings']['in_stock_processing'] = 'in_stock_only' if watch.get(
                'in_stock_only') else 'all_changes'

            if self.data['watching'][uuid].get('in_stock_only'):
                del (self.data['watching'][uuid]['in_stock_only'])

    def update_19(self):
        """Compress old elements.json to elements.deflate, saving disk, this compression is pretty fast."""
        import zlib

        for uuid, watch in self.data['watching'].items():
            json_path = os.path.join(self.datastore_path, uuid, "elements.json")
            deflate_path = os.path.join(self.datastore_path, uuid, "elements.deflate")

            if os.path.exists(json_path):
                with open(json_path, "rb") as f_j:
                    with open(deflate_path, "wb") as f_d:
                        logger.debug(f"Compressing {str(json_path)} to {str(deflate_path)}..")
                        f_d.write(zlib.compress(f_j.read()))
                        os.unlink(json_path)

    def update_20(self):
        """Migrate extract_title_as_title to use_page_title_in_list."""
        for uuid, watch in self.data['watching'].items():
            if self.data['watching'][uuid].get('extract_title_as_title'):
                self.data['watching'][uuid]['use_page_title_in_list'] = self.data['watching'][uuid].get('extract_title_as_title')
                del self.data['watching'][uuid]['extract_title_as_title']

        if self.data['settings']['application'].get('extract_title_as_title'):
            self.data['settings']['application']['ui']['use_page_title_in_list'] = self.data['settings']['application'].get('extract_title_as_title')

    def update_21(self):
        """Migrate timezone to scheduler_timezone_default."""
        if self.data['settings']['application'].get('timezone'):
            self.data['settings']['application']['scheduler_timezone_default'] = self.data['settings']['application'].get('timezone')
            del self.data['settings']['application']['timezone']

    def update_23(self):
        """Some notification formats got the wrong name type."""

        def re_run(formats):
            sys_n_format = self.data['settings']['application'].get('notification_format')
            key_exists_as_value = next((k for k, v in formats.items() if v == sys_n_format), None)
            if key_exists_as_value:  # key of "Plain text"
                logger.success(f"['settings']['application']['notification_format'] '{sys_n_format}' -> '{key_exists_as_value}'")
                self.data['settings']['application']['notification_format'] = key_exists_as_value

            for uuid, watch in self.data['watching'].items():
                n_format = self.data['watching'][uuid].get('notification_format')
                key_exists_as_value = next((k for k, v in formats.items() if v == n_format), None)
                if key_exists_as_value and key_exists_as_value != USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:  # key of "Plain text"
                    logger.success(f"['watching'][{uuid}]['notification_format'] '{n_format}' -> '{key_exists_as_value}'")
                    self.data['watching'][uuid]['notification_format'] = key_exists_as_value  # should be 'text' or whatever

            for uuid, tag in self.data['settings']['application']['tags'].items():
                n_format = self.data['settings']['application']['tags'][uuid].get('notification_format')
                key_exists_as_value = next((k for k, v in formats.items() if v == n_format), None)
                if key_exists_as_value and key_exists_as_value != USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:  # key of "Plain text"
                    logger.success(
                        f"['settings']['application']['tags'][{uuid}]['notification_format'] '{n_format}' -> '{key_exists_as_value}'")
                    self.data['settings']['application']['tags'][uuid][
                        'notification_format'] = key_exists_as_value  # should be 'text' or whatever

        from ..notification import valid_notification_formats
        formats = deepcopy(valid_notification_formats)
        re_run(formats)
        # And in previous versions, it was "text" instead of Plain text, Markdown instead of "Markdown to HTML"
        formats['text'] = 'Text'
        formats['markdown'] = 'Markdown'
        re_run(formats)

    def update_24(self):
        """RSS types should be inline with the same names as notification types."""
        rss_format = self.data['settings']['application'].get('rss_content_format')
        if not rss_format or 'text' in rss_format:
            # might have been 'plaintext, 'plain text' or something
            self.data['settings']['application']['rss_content_format'] = RSS_CONTENT_FORMAT_DEFAULT
        elif 'html' in rss_format:
            self.data['settings']['application']['rss_content_format'] = 'htmlcolor'
        else:
            # safe fallback to text
            self.data['settings']['application']['rss_content_format'] = RSS_CONTENT_FORMAT_DEFAULT

    def update_25(self):
        """Different processors now hold their own history.txt."""
        for uuid, watch in self.data['watching'].items():
            processor = self.data['watching'][uuid].get('processor')
            if processor != 'text_json_diff':
                old_history_txt = os.path.join(self.datastore_path, "history.txt")
                target_history_name = f"history-{processor}.txt"
                if os.path.isfile(old_history_txt) and not os.path.isfile(target_history_name):
                    new_history_txt = os.path.join(self.datastore_path, target_history_name)
                    logger.debug(f"Renaming history index {old_history_txt} to {new_history_txt}...")
                    shutil.move(old_history_txt, new_history_txt)

    def migrate_legacy_db_format(self):
        """
        Migration: Individual watch persistence (COPY-based, safe rollback).

        Loads legacy url-watches.json format and migrates to:
        - {uuid}/watch.json (per watch)
        - changedetection.json (settings only)

        IMPORTANT:
        - A tarball backup (before-update-26-timestamp.tar.gz) is created before migration
        - url-watches.json is LEFT INTACT for rollback safety
        - Users can roll back by simply downgrading to the previous version
        - Or restore from tarball: tar -xzf before-update-26-*.tar.gz

        This is a dedicated migration release - users upgrade at their own pace.
        """
        logger.critical("=" * 80)
        logger.critical("Running migration: Individual watch persistence (update_26)")
        logger.critical("COPY-based migration: url-watches.json will remain intact for rollback")
        logger.critical("=" * 80)

        # Check if already migrated
        changedetection_json = os.path.join(self.datastore_path, "changedetection.json")
        if os.path.exists(changedetection_json):
            logger.info("Migration already completed (changedetection.json exists), skipping")
            return

        # Check if we need to load legacy data
        from .legacy_loader import has_legacy_datastore, load_legacy_format

        if not has_legacy_datastore(self.datastore_path):
            logger.info("No legacy datastore found, nothing to migrate")
            return

        # Load legacy data from url-watches.json
        logger.critical("Loading legacy datastore from url-watches.json...")
        legacy_path = os.path.join(self.datastore_path, "url-watches.json")
        legacy_data = load_legacy_format(legacy_path)

        if not legacy_data:
            raise Exception("Failed to load legacy datastore from url-watches.json")

        # Populate settings from legacy data
        logger.info("Populating settings from legacy data...")
        watch_count = len(self.data['watching'])
        logger.success(f"Loaded {watch_count} watches from legacy format")

        # Phase 1: Save all watches to individual files
        logger.critical(f"Phase 1/4: Saving {watch_count} watches to individual watch.json files...")

        saved_count = 0
        for uuid, watch in self.data['watching'].items():
            try:
                watch_dict = dict(watch)
                watch_dir = os.path.join(self.datastore_path, uuid)
                save_watch_atomic(watch_dir, uuid, watch_dict)
                saved_count += 1

                if saved_count % 100 == 0:
                    logger.info(f"  Progress: {saved_count}/{watch_count} watches migrated...")

            except Exception as e:
                logger.error(f"Failed to save watch {uuid}: {e}")
                raise Exception(
                    f"Migration failed: Could not save watch {uuid}. "
                    f"url-watches.json remains intact, safe to retry. Error: {e}"
                )

        logger.critical(f"Phase 1 complete: Saved {saved_count} watches")

        # Phase 2: Verify all files exist
        logger.critical("Phase 2/4: Verifying all watch.json files were created...")

        missing = []
        for uuid in self.data['watching'].keys():
            watch_json = os.path.join(self.datastore_path, uuid, "watch.json")
            if not os.path.isfile(watch_json):
                missing.append(uuid)

        if missing:
            raise Exception(
                f"Migration failed: {len(missing)} watch files missing: {missing[:5]}... "
                f"url-watches.json remains intact, safe to retry."
            )

        logger.critical(f"Phase 2 complete: Verified {watch_count} watch files")

        # Phase 3: Create new settings file
        logger.critical("Phase 3/4: Creating changedetection.json...")

        try:
            self._save_settings()
        except Exception as e:
            logger.error(f"Failed to create changedetection.json: {e}")
            raise Exception(
                f"Migration failed: Could not create changedetection.json. "
                f"url-watches.json remains intact, safe to retry. Error: {e}"
            )

        # Phase 4: Verify settings file exists
        logger.critical("Phase 4/4: Verifying changedetection.json exists...")

        if not os.path.isfile(changedetection_json):
            raise Exception(
                "Migration failed: changedetection.json not found after save. "
                "url-watches.json remains intact, safe to retry."
            )

        logger.critical("Phase 4 complete: Verified changedetection.json exists")

        # Success! Now reload from new format
        logger.critical("Reloading datastore from new format...")
        self._load_state() # Includes load_watches
        logger.success("Datastore reloaded from new format successfully")
        logger.critical("=" * 80)
        logger.critical("MIGRATION COMPLETED SUCCESSFULLY!")
        logger.critical("=" * 80)
        logger.info("")
        logger.info("New format:")
        logger.info(f"  - {watch_count} individual watch.json files created")
        logger.info(f"  - changedetection.json created (settings only)")
        logger.info("")
        logger.info("Rollback safety:")
        logger.info("  - url-watches.json preserved for rollback")
        logger.info("  - To rollback: downgrade to previous version and restart")
        logger.info("  - No manual file operations needed")
        logger.info("")
        logger.info("Optional cleanup (after testing new version):")
        logger.info(f"  - rm {os.path.join(self.datastore_path, 'url-watches.json')}")
        logger.info("")

    def update_26(self):
        self.migrate_legacy_db_format()

    def update_28(self):
        """
        Migrate tags to individual tag.json files.

        Tags are currently saved only in changedetection.json (settings).
        This migration ALSO saves them to individual {uuid}/tag.json files,
        similar to how watches are stored (dual storage).

        Benefits:
        - Allows atomic tag updates without rewriting entire settings
        - Enables independent tag versioning/backup
        - Maintains backwards compatibility (tags stay in settings too)
        """
        logger.critical("=" * 80)
        logger.critical("Running migration: Individual tag persistence (update_28)")
        logger.critical("Creating individual tag.json files (tags remain in settings too)")
        logger.critical("=" * 80)

        tags = self.data['settings']['application'].get('tags', {})
        tag_count = len(tags)

        if tag_count == 0:
            logger.info("No tags found, skipping migration")
            return

        logger.info(f"Migrating {tag_count} tags to individual tag.json files...")

        saved_count = 0
        failed_count = 0

        for uuid, tag_data in tags.items():
            try:
                # Force save as tag.json (not watch.json) even if object is corrupted
                from changedetectionio.store.file_saving_datastore import save_entity_atomic
                import os

                tag_dir = os.path.join(self.datastore_path, uuid)
                os.makedirs(tag_dir, exist_ok=True)

                # Convert to dict if it's an object
                tag_dict = dict(tag_data) if hasattr(tag_data, '__iter__') else tag_data

                # Save explicitly as tag.json
                save_entity_atomic(
                    tag_dir,
                    uuid,
                    tag_dict,
                    filename='tag.json',
                    entity_type='tag',
                    max_size_mb=1
                )
                saved_count += 1

                if saved_count % 10 == 0:
                    logger.info(f"  Progress: {saved_count}/{tag_count} tags migrated...")

            except Exception as e:
                logger.error(f"Failed to save tag {uuid} ({tag_data.get('title', 'unknown')}): {e}")
                failed_count += 1

        if failed_count > 0:
            logger.warning(f"Migration complete: {saved_count} tags saved, {failed_count} tags FAILED")
        else:
            logger.success(f"Migration complete: {saved_count} tags saved to individual tag.json files")

        # Tags remain in settings for backwards compatibility AND easy access
        # On next load, _load_tags() will read from tag.json files and merge with settings
        logger.info("Tags saved to both settings AND individual tag.json files")
        logger.info("Future tag edits will update both locations (dual storage)")

        logger.critical("=" * 80)