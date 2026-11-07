#!/usr/bin/env python3
# OAuth 2.0 client credentials for watches of APIs that want a bearer token (#375)

import json
import os

from flask import url_for

from changedetectionio import oauth2

from .util import delete_all_watches, wait_for_all_checks


def oauth_state(datastore_path):
    try:
        with open(os.path.join(datastore_path, 'oauth-state.json')) as f:
            return json.load(f)
    except OSError:
        return {'requests': [], 'valid': []}


def revoke_all_tokens(datastore_path):
    state = oauth_state(datastore_path)
    state['valid'] = []
    with open(os.path.join(datastore_path, 'oauth-state.json'), 'w') as f:
        json.dump(state, f)


def reset_oauth(datastore_path):
    oauth2.clear_cache()
    path = os.path.join(datastore_path, 'oauth-state.json')
    if os.path.exists(path):
        os.unlink(path)


def edit_watch(client, uuid, test_url, **fields):
    data = {
        "url": test_url,
        "tags": "",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y",
        "oauth2_token_url": url_for('test_oauth_token', _external=True),
        "oauth2_client_id": "cd-client",
        "oauth2_client_secret": "cd-secret",
        "oauth2_scope": "read:prices",
        "oauth2_client_auth": "basic",
    }
    data.update(fields)
    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid), data=data, follow_redirects=True)
    assert b"Updated watch." in res.data
    return res


def check(client):
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)


def preview(client, uuid):
    return client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True).data


def test_bearer_token_is_fetched_and_reused(client, live_server, measure_memory_usage, datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_oauth_protected', _external=True)
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=test_url)
    edit_watch(client, uuid, test_url)
    check(client)

    assert b"Price list for subscribers: 42 EUR" in preview(client, uuid)
    requests = oauth_state(datastore_path)['requests']
    assert len(requests) == 1
    assert requests[0]['basic'] is True
    assert requests[0]['form'] == {'grant_type': 'client_credentials', 'scope': 'read:prices'}

    # the next check reuses the token rather than asking for another
    check(client)
    assert len(oauth_state(datastore_path)['requests']) == 1
    assert not datastore.data['watching'][uuid].get('last_error')

    delete_all_watches(client)


def test_a_refused_token_is_replaced_on_the_next_check(client, live_server, measure_memory_usage, datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_oauth_protected', _external=True)
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=test_url)
    edit_watch(client, uuid, test_url)
    check(client)
    assert b"(with tok-1)" in preview(client, uuid)

    # the API revokes the token: that check fails, and the token is forgotten
    revoke_all_tokens(datastore_path)
    check(client)
    assert '401' in str(datastore.data['watching'][uuid].get('last_error'))

    # so the next one gets a new token, and works again
    check(client)
    assert not datastore.data['watching'][uuid].get('last_error')
    assert len(oauth_state(datastore_path)['requests']) == 2
    assert b"(with tok-2)" in preview(client, uuid)

    delete_all_watches(client)


def test_credentials_in_the_body_and_an_audience(client, live_server, measure_memory_usage, datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_oauth_protected', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    edit_watch(client, uuid, test_url, oauth2_client_auth='body', oauth2_audience='https://api.example.com',
               oauth2_scope='')
    check(client)

    assert b"Price list for subscribers" in preview(client, uuid)
    request = oauth_state(datastore_path)['requests'][0]
    assert request['basic'] is False
    assert request['form'] == {'grant_type': 'client_credentials', 'audience': 'https://api.example.com',
                               'client_id': 'cd-client', 'client_secret': 'cd-secret'}

    delete_all_watches(client)


def test_a_bad_secret_is_reported_on_the_watch(client, live_server, measure_memory_usage, datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_oauth_protected', _external=True)
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=test_url)
    edit_watch(client, uuid, test_url, oauth2_client_secret='wrong')
    check(client)

    error = str(datastore.data['watching'][uuid].get('last_error'))
    assert 'OAuth token request failed (401)' in error
    assert 'invalid_client' in error
    res = client.get(url_for("watchlist.index"))
    assert b'OAuth token request failed (401)' in res.data

    delete_all_watches(client)


def test_an_authorization_header_takes_its_place(client, live_server, measure_memory_usage, datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_headers', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    edit_watch(client, uuid, test_url, headers="Authorization: Bearer set-by-hand")
    check(client)

    assert b"Authorization:Bearer set-by-hand" in preview(client, uuid)
    assert oauth_state(datastore_path)['requests'] == []

    delete_all_watches(client)


def test_the_secret_is_kept_hidden_and_cleared_with_the_token_url(client, live_server, measure_memory_usage,
                                                                  datastore_path):
    reset_oauth(datastore_path)
    test_url = url_for('test_oauth_protected', _external=True)
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=test_url)
    edit_watch(client, uuid, test_url)

    # never sent back to the page
    page = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid)).data
    assert b'cd-secret' not in page
    assert b'leave empty to keep it' in page

    # saved again with the field left empty, it is kept
    edit_watch(client, uuid, test_url, oauth2_client_secret='')
    assert datastore.data['watching'][uuid]['oauth2_client_secret'] == 'cd-secret'

    # nor returned by the API
    api_key = datastore.data['settings']['application'].get('api_access_token')
    res = client.get(url_for("watch", uuid=uuid), headers={'x-api-key': api_key})
    assert res.json['oauth2_client_id'] == 'cd-client'
    assert 'oauth2_client_secret' not in res.json

    # clearing the token URL switches OAuth off, and forgets the secret
    edit_watch(client, uuid, test_url, oauth2_token_url='', oauth2_client_secret='')
    assert datastore.data['watching'][uuid]['oauth2_client_secret'] == ''

    delete_all_watches(client)


def test_the_form_and_the_api_check_the_settings(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_oauth_protected', _external=True)
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=test_url)

    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid),
                      data={"url": test_url, "tags": "", "fetch_backend": "html_requests",
                            "time_between_check_use_default": "y",
                            "oauth2_token_url": url_for('test_oauth_token', _external=True), "oauth2_client_id": ""},
                      follow_redirects=True)
    assert b"A client ID is needed with an OAuth 2.0 token URL" in res.data

    res = client.post(url_for("ui.ui_edit.edit_page", uuid=uuid),
                      data={"url": test_url, "tags": "", "fetch_backend": "html_requests",
                            "time_between_check_use_default": "y",
                            "oauth2_token_url": "javascript:alert(1)", "oauth2_client_id": "x"},
                      follow_redirects=True)
    assert b"Updated watch." not in res.data

    api_key = datastore.data['settings']['application'].get('api_access_token')
    res = client.post(url_for("createwatch"),
                      data=json.dumps({"url": test_url, "oauth2_token_url": "javascript:alert(1)"}),
                      headers={'content-type': 'application/json', 'x-api-key': api_key})
    assert res.status_code == 400
    assert b"oauth2_token_url" in res.data

    res = client.post(url_for("createwatch"),
                      data=json.dumps({"url": test_url, "oauth2_token_url": url_for('test_oauth_token', _external=True),
                                       "oauth2_client_id": "cd-client", "oauth2_client_secret": "cd-secret"}),
                      headers={'content-type': 'application/json', 'x-api-key': api_key})
    assert res.status_code == 201

    delete_all_watches(client)


def test_the_token_url_passes_the_fetch_gate(monkeypatch):
    """The token URL is a server-side fetch, so it is checked like the watch URL (private addresses and so on)."""
    import changedetectionio.validate_url as validate_url
    oauth2.clear_cache()
    monkeypatch.setattr(validate_url, 'is_fetch_url_allowed', lambda url: (False, 'private address'))
    watch = {'oauth2_token_url': 'http://169.254.169.254/token', 'oauth2_client_id': 'x', 'oauth2_client_secret': 'y'}
    try:
        oauth2.get_access_token(watch)
    except oauth2.OAuth2Error as e:
        assert 'not allowed: private address' in str(e)
    else:
        raise AssertionError('the token URL was fetched without being checked')
