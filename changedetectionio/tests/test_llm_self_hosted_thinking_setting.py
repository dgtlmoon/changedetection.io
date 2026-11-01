#!/usr/bin/env python3
"""
The "Switch thinking off" checkbox for OpenAI-compatible endpoints (llama.cpp etc, #4638): shown on the AI settings
page, off unless ticked, and saved with the provider connection.
"""
from flask import url_for

from changedetectionio.tests.util import delete_all_watches

FORM = {
    'llm-model': 'openai/lfm3-1.7b',
    'llm-api_key': '',
    'llm-api_base': 'http://127.0.0.1:8080/v1',
    'llm-provider_kind': 'openai_compatible',
    'application-pager_size': '50',
    'application-notification_format': 'html',
    'application-fetch_backend': 'html_requests',
    'application-rss_diff_length': '5',
    'application-filter_failure_notification_threshold_attempts': '0',
    'requests-time_between_check-days': '0',
    'requests-time_between_check-hours': '0',
    'requests-time_between_check-minutes': '5',
    'requests-time_between_check-seconds': '0',
    'requests-time_between_check-weeks': '0',
    'requests-jitter_seconds': '0',
    'requests-workers': '10',
    'requests-timeout': '60',
}


def test_local_thinking_off_setting(client, live_server, measure_memory_usage, datastore_path):
    ds = client.application.config.get('DATASTORE')

    res = client.get(url_for('settings.llm.llm_settings_page'))
    assert b'id="llm-local_thinking_off"' in res.data
    assert b'llm-local-thinking-group' in res.data

    # Not ticked: saved as off, so the server's own thinking default applies
    res = client.post(url_for('settings.llm.llm_settings_page'), data=FORM, follow_redirects=True)
    assert b'Settings updated.' in res.data
    assert ds.data['settings']['application']['llm'].get('local_thinking_off') is False

    res = client.post(url_for('settings.llm.llm_settings_page'), data={**FORM, 'llm-local_thinking_off': 'y'},
                      follow_redirects=True)
    assert b'Settings updated.' in res.data
    assert ds.data['settings']['application']['llm']['local_thinking_off'] is True

    delete_all_watches(client)
