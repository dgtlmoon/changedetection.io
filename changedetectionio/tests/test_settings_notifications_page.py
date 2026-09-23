#!/usr/bin/env python3
"""
Tests for the /settings/notifications page (separated from the main /settings
form in 2026). The notification config lives at
    datastore.data['settings']['application']['notification_*']
and is now edited via its own form + route. The main settings page must NOT
clobber those values when an unrelated section (workers, RSS, etc.) is saved,
because both pages mutate the same `application` dict.
"""

from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches


def _seed_notification_config(datastore):
    """Pre-load the notification config into the application settings dict."""
    app = datastore.data['settings']['application']
    app['notification_urls'] = ['json://example.invalid/preserved']
    app['notification_title'] = 'Preserved title - {{ watch_url }}'
    app['notification_body'] = 'Preserved body - {{ diff }}'
    app['notification_format'] = 'html'
    app['base_url'] = 'https://preserved.example/'


def test_notifications_page_renders_form_inputs(
        client, live_server, measure_memory_usage, datastore_path):
    """Smoke test that the standalone /settings/notifications template actually
    renders the form. Catches template-level regressions — bad macro import,
    missing field, broken Jinja, etc. — that would still return HTTP 200 but
    silently drop the input boxes.

    Scans for each field's `name="..."` attribute (widget-agnostic — works for
    StringField/TextAreaField/SelectField/StringListField alike) plus the
    submit button and the notifications.js wiring."""
    res = client.get(url_for('settings.notifications.apprise'))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    for field in ('notification_urls', 'notification_title', 'notification_body',
                  'notification_format', 'base_url'):
        assert f'name="{field}"' in body, \
            f"Form input for {field!r} missing from /settings/notifications HTML"

    # Submit form actually wired to the right route
    assert f'action="{url_for("settings.notifications.apprise")}"' in body, \
        "Form should POST back to /settings/notifications/apprise"

    # notifications.js needs the JS-side ajax endpoint to test sends from this page
    assert 'notification_base_url' in body, \
        "notifications.js depends on notification_base_url being defined"
    assert 'send-test-notification' in body, \
        "'Send test notification' button missing — notifications.js binds to it"

    # The page uses the same tab UI scaffolding as /settings so the page styles
    # the same way (collapsable tabs wrapper, single 'All Notifications' tab,
    # tabs.js loaded). Catches regressions where the tab markup gets stripped
    # back out, which would visually break the layout.
    assert 'class="tabs collapsable"' in body, \
        "Tabs wrapper missing — page won't get the standard settings styling"
    assert 'href="#all-notifications"' in body, \
        "'All Notifications' tab anchor missing"
    assert 'id="all-notifications"' in body, \
        "tab-pane-inner target #all-notifications missing — tab would be inert"
    assert 'tabs.js' in body, \
        "tabs.js not loaded — the tab UI won't activate"


def test_notifications_page_get_renders_stored_values(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /settings/notifications must render the values currently in storage."""
    ds = client.application.config.get('DATASTORE')
    _seed_notification_config(ds)

    res = client.get(url_for('settings.notifications.apprise'))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')

    assert 'json://example.invalid/preserved' in body, \
        "Stored notification URL must be rendered in the form"
    assert 'Preserved title' in body
    assert 'Preserved body' in body
    assert 'https://preserved.example/' in body, \
        "Stored base_url must be rendered in the form"


def test_notifications_page_post_saves_values(
        client, live_server, measure_memory_usage, datastore_path):
    """POST to /settings/notifications must persist the submitted notification
    fields into application settings."""
    ds = client.application.config.get('DATASTORE')

    res = client.post(
        url_for('settings.notifications.apprise'),
        data={
            'notification_urls': 'json://example.invalid/new',
            'notification_title': 'New title - {{ watch_url }}',
            'notification_body': 'New body',
            'notification_format': 'html',
            'base_url': 'https://new.example/',
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b'Settings updated.' in res.data, \
        "Notification settings save did not flash success"

    app = ds.data['settings']['application']
    assert 'json://example.invalid/new' in (app.get('notification_urls') or [])
    assert app.get('notification_title') == 'New title - {{ watch_url }}'
    assert app.get('notification_body') == 'New body'
    assert app.get('notification_format') == 'html'
    assert app.get('base_url') == 'https://new.example/'


def test_main_settings_save_does_not_clobber_notification_config(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Regression — the main /settings page and the new /settings/notifications page
    write to the SAME dict (datastore.data['settings']['application']). The main
    page's application sub-form still inherits the notification_* fields from
    commonSettingsForm, so a naive `app.update(form.data['application'])` here
    would wipe notification_urls / title / body / format / base_url with empty
    WTForms defaults whenever the user saves the main settings page.

    This test seeds a real notification config, then POSTs the main settings
    page WITHOUT touching the notification fields, and asserts every notification
    value survived the unrelated save.
    """
    ds = client.application.config.get('DATASTORE')
    _seed_notification_config(ds)

    res = client.post(
        url_for('settings.settings_page'),
        data={
            # Minimal payload to validate the main form. Must NOT include any
            # of the notification fields — that's the whole point of the test.
            'application-pager_size': '50',
            'application-fetch_backend': 'html_requests',
            'application-rss_diff_length': '5',
            'application-filter_failure_notification_threshold_attempts': '0',
            'application-notification_format': 'html',  # required choice, no Optional()
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-jitter_seconds': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b'Settings updated.' in res.data, \
        "Main settings save didn't reach the success branch — test setup is wrong"

    app = ds.data['settings']['application']
    assert app.get('notification_urls') == ['json://example.invalid/preserved'], \
        f"Main settings save clobbered notification_urls (got {app.get('notification_urls')!r})"
    assert app.get('notification_title') == 'Preserved title - {{ watch_url }}', \
        f"Main settings save clobbered notification_title (got {app.get('notification_title')!r})"
    assert app.get('notification_body') == 'Preserved body - {{ diff }}', \
        f"Main settings save clobbered notification_body (got {app.get('notification_body')!r})"
    assert app.get('base_url') == 'https://preserved.example/', \
        f"Main settings save clobbered base_url (got {app.get('base_url')!r})"

    delete_all_watches(client)


def test_notifications_page_save_does_not_clobber_other_settings(
        client, live_server, measure_memory_usage, datastore_path):
    """
    Inverse of the above — saving notifications must NOT reach over and zero
    out unrelated application settings (pager_size, fetch_backend, etc.).

    The notifications-page handler explicitly writes a known list of five
    notification fields rather than doing app.update(form.data) — this test
    pins that behaviour so a refactor that switches to .update() (which would
    silently zero out every non-notification key) fails loudly here.
    """
    ds = client.application.config.get('DATASTORE')
    app = ds.data['settings']['application']
    # Plant a representative mix of application-level fields: ints, lists,
    # strings, bools, nested dicts. If the notifications save ever does a
    # blanket .update(form.data) it'll wipe these to WTForms defaults and
    # the per-field asserts below will catch it.
    untouched_snapshot = {
        'pager_size': 73,
        'fetch_backend': 'html_requests',
        'rss_diff_length': 9,
        'filter_failure_notification_threshold_attempts': 4,
        'global_ignore_text': ['SENTINEL-IGNORE-LINE'],
        'global_subtractive_selectors': ['nav.SENTINEL-SUB'],
        'ignore_whitespace': True,
        'render_anchor_tag_content': True,
        'shared_diff_access': True,
        'api_access_token_enabled': False,
        'scheduler_timezone_default': 'Europe/Berlin',
    }
    for k, v in untouched_snapshot.items():
        app[k] = v

    res = client.post(
        url_for('settings.notifications.apprise'),
        data={
            'notification_urls': 'json://example.invalid/only-this',
            'notification_title': '',
            'notification_body': '',
            'notification_format': 'html',
            'base_url': '',
        },
        follow_redirects=True,
    )
    assert res.status_code == 200
    assert b'Settings updated.' in res.data, \
        "Notification save did not reach the success branch — test setup is wrong"

    # Every planted field must have survived the notifications save bit-for-bit.
    for k, expected in untouched_snapshot.items():
        actual = ds.data['settings']['application'].get(k)
        assert actual == expected, \
            f"Notification save clobbered unrelated setting {k!r}: expected {expected!r}, got {actual!r}"

    # And the notification field we DID submit was actually written.
    assert ds.data['settings']['application'].get('notification_urls') == \
        ['json://example.invalid/only-this']
