import os
import pytest
from flask import url_for
from .util import set_original_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, set_modified_response

def test_rss_tag_feed_ignores_security_token(client, live_server, datastore_path):
    # Enable password authentication via settings endpoint
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-password": "password",
            "application-empty_pages_are_a_change": "y"
        },
        follow_redirects=True
    )
    assert b'Password protection enabled' in res.data or client.application.config['DATASTORE'].data['settings']['application'].get('password')

    # Add a watch using datastore
    url = url_for('test_endpoint', _external=True)
    uuid = client.application.config['DATASTORE'].add_watch(url=url)
    watch = client.application.config['DATASTORE'].data['watching'][uuid]

    # Create tag
    import uuid
    tag_uuid = str(uuid.uuid4())
    client.application.config['DATASTORE'].data['settings']['application'].setdefault('tags', {})[tag_uuid] = {'title': 'my-tag'}
    # Assign tag to watch
    watch.get('tags').append(tag_uuid)

    wait_for_all_checks(client)

    # Get the token
    rss_token = extract_rss_token_from_UI(client)

    # Trigger a change so we have history and an unviewed change
    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Logout
    client.get(url_for("logout"), follow_redirects=True)

    # Request the tag RSS feed WITH the token
    res = client.get(
        url_for("rss.rss_tag_feed", tag_uuid=tag_uuid, token=rss_token, _external=True),
        follow_redirects=False # Do not follow redirects because it would redirect to login if auth is failing
    )

    # It should be 200 OK
    assert res.status_code == 200, f"Expected 200, got {res.status_code} and data {res.data}"
    assert b'xml' in res.data
