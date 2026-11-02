import hashlib

# Plugins import only from changedetectionio.plugin_api, everything else is internal and may change
from changedetectionio.plugin_api import difference_detection_processor

name = 'Word counter (example plugin)'
description = 'Counts the words on the page, a change is when the count changes'


class perform_site_check(difference_detection_processor):

    def run_changedetection(self, watch, force_reprocess=False):
        from changedetectionio.plugin_api import html_to_text, get_resolved_processor_config
        from . import PROCESSOR_NAME

        # Same resolution as the API shows in processor_config_word_counter (a tag with 'overrides_watch' wins)
        config, _source = get_resolved_processor_config(self.datastore, watch)
        min_word_length = int(config.get('min_word_length') or 1)

        text = html_to_text(self.fetcher.content or '')
        word_count = len([w for w in text.split() if len(w) >= min_word_length])

        # What goes in the history, and what the diff page compares
        snapshot_content = f"Words: {word_count}"
        fetched_md5 = hashlib.md5(snapshot_content.encode('utf-8')).hexdigest()
        changed_detected = bool(watch.get('previous_md5')) and watch.get('previous_md5') != fetched_md5

        update_obj = {
            'last_notification_error': False,
            'last_error': False,
            'last_check_status': self.fetcher.get_last_status_code(),
            'previous_md5': fetched_md5,
            # Saved on the watch, published by get_api_watch_processor_state() in __init__.py
            # @IMPORTANT-TODO: interim, there is no processor storage convention yet, see store update_watch()
            f'processor_state_{PROCESSOR_NAME}': {'word_count': word_count},
        }

        return changed_detected, update_obj, snapshot_content
