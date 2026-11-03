#!/usr/bin/env python3
"""The notification setup widget: its JSON endpoints, and that it's on every page with notification URLs."""
import json

from flask import url_for

from .util import delete_all_watches, wait_for_all_checks


def test_notification_setup_endpoints(client, live_server, measure_memory_usage, datastore_path):
    res = client.get(url_for('settings.notifications.apprise_services'))
    assert res.status_code == 200
    schemas = {s['schema']: s['name'] for s in res.json}
    assert schemas['discord'] == 'Discord'
    assert schemas['mailtos'] == 'Custom e-mail'

    res = client.get(url_for('settings.notifications.apprise_services', q='telegr'))
    assert [s['schema'] for s in res.json] == ['tgram']

    res = client.get(url_for('settings.notifications.apprise_service', schema='tgram'))
    assert res.status_code == 200
    assert res.json['fields'][0]['key'] == 'bot_token'

    res = client.get(url_for('settings.notifications.apprise_service', schema='not-a-service'))
    assert res.status_code == 404

    def build(payload):
        return client.post(url_for('settings.notifications.apprise_build'), data=json.dumps(payload),
                           content_type='application/json')

    res = build({'schema': 'discord', 'values': {'webhook_id': '1234567', 'webhook_token': 'abcdefghijk'}})
    assert res.status_code == 200
    assert res.json['url'] == 'discord://1234567/abcdefghijk/'
    assert 'abcdefghijk' not in res.json['url_masked']

    res = build({'schema': 'discord', 'values': {'webhook_id': '1234567'}})
    assert res.status_code == 400
    assert res.json['missing'] == ['Webhook Token']

    assert build({}).status_code == 400


def test_notification_setup_widget_on_pages(client, live_server, measure_memory_usage, datastore_path):
    widget = b'id="notification-setup"'

    res = client.get(url_for('settings.notifications.apprise'))
    assert widget in res.data
    # Labels for the JS are passed as escaped JSON in an attribute
    assert b'data-i18n="{&#34;' in res.data
    assert b'notification-setup.js' in res.data
    # The existing textarea is still there, the widget only appends to it
    assert b'name="notification_urls"' in res.data

    res = client.post(url_for('ui.ui_views.form_quick_watch_add'),
                      data={'url': url_for('test_endpoint', _external=True), 'tags': ''}, follow_redirects=True)
    assert b'Watch added' in res.data
    wait_for_all_checks(client)
    res = client.get(url_for('ui.ui_edit.edit_page', uuid='first'))
    assert widget in res.data

    res = client.post(url_for('tags.form_tag_add'), data={'name': 'setup-widget-tag'}, follow_redirects=True)
    assert b'Tag added' in res.data
    res = client.get(url_for('tags.form_tag_edit', uuid='first'))
    assert widget in res.data

    client.post(url_for('tags.delete_all'), follow_redirects=True)
    delete_all_watches(client)
