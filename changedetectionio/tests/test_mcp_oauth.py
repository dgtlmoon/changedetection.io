#!/usr/bin/env python3
"""MCP OAuth sign-in (blueprint/mcp/oauth): discovery from the 401, the metadata documents, only offered with MCP on
and a password set, and nothing of Authlib loaded until it's used."""
import json

import pytest
from flask import url_for


@pytest.fixture(autouse=True)
def mcp_on_with_password(client):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    settings['mcp_enabled'] = True
    settings['password'] = 'something'
    yield
    settings['password'] = False


def _ping(client, headers=None):
    return client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
                       content_type='application/json', headers=headers or {})


def test_discovery(client, live_server, measure_memory_usage, datastore_path):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    base = url_for('mcp.endpoint', _external=True).rsplit('/mcp/v1', 1)[0]

    # A request without a token is told where the sign-in is (RFC 9728)
    res = _ping(client)
    assert res.status_code == 401
    challenge = res.headers['WWW-Authenticate']
    assert challenge.startswith('Bearer ') and f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp/v1"' in challenge
    assert 'scope="mcp"' in challenge

    # The resource metadata, at the path-specific address clients try first and the root one
    for path in ('/.well-known/oauth-protected-resource/mcp/v1', '/.well-known/oauth-protected-resource'):
        res = client.get(path)
        assert res.status_code == 200, path
        assert res.json['resource'] == f'{base}/mcp/v1' and res.json['authorization_servers'] == [base]

    # The authorization server metadata: what MCP clients check before going on
    meta = client.get('/.well-known/oauth-authorization-server').json
    assert meta['issuer'] == base
    assert meta['code_challenge_methods_supported'] == ['S256']
    assert meta['token_endpoint_auth_methods_supported'] == ['none'], "public clients only, CIMD has no secrets"
    assert meta['client_id_metadata_document_supported'] is True
    assert meta['authorization_response_iss_parameter_supported'] is True
    assert meta['authorization_endpoint'] == f'{base}/oauth/authorize' and meta['token_endpoint'] == f'{base}/oauth/token'

    # Also at {issuer}/.well-known/openid-configuration: behind a path prefix (/big-balls/mcp/v1), RFC 8414's address is
    # at the host root and never reaches the instance, and this is where clients look next
    assert client.get('/.well-known/openid-configuration').json == meta

    # Behind a proxy, the Base URL setting is the address clients see
    settings['base_url'] = 'https://cd.example.com/instance/'
    try:
        meta = client.get('/.well-known/oauth-authorization-server').json
        assert meta['issuer'] == 'https://cd.example.com/instance'
        assert 'https://cd.example.com/instance/.well-known/oauth-protected-resource/mcp/v1' in _ping(client).headers['WWW-Authenticate']
    finally:
        settings['base_url'] = ''


def test_only_offered_with_mcp_on_and_a_password(client, live_server, measure_memory_usage, datastore_path):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    paths = ('/.well-known/oauth-protected-resource', '/.well-known/oauth-protected-resource/mcp/v1',
             '/.well-known/oauth-authorization-server', '/.well-known/openid-configuration')

    # No password: no login to sit behind, so no sign-in, and the 401 doesn't point at one
    settings['password'] = False
    for path in paths:
        assert client.get(path).status_code == 404, path
    res = _ping(client)
    assert res.status_code == 401 and 'resource_metadata' not in res.headers['WWW-Authenticate']
    # The OAuth sub-tab says why, linking to where the password is set (the link comes from the template, not the translation)
    html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
    assert f'<a href="{url_for("settings.settings_page")}#general">set a password</a>' in html

    # MCP switched off: everything is a 404, like /mcp/v1 itself
    settings['password'] = 'something'
    settings['mcp_enabled'] = False
    for path in paths:
        assert client.get(path).status_code == 404, path
    assert _ping(client).status_code == 404
    settings['mcp_enabled'] = True


def test_oauth_imported_lazily():
    # Authlib (and joserfc) must not load by starting the app or importing the OAuth routes, only on a sign-in
    import os
    import subprocess
    import sys
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ("import sys, changedetectionio.flask_app, changedetectionio.blueprint.mcp, "
            "changedetectionio.blueprint.mcp.oauth; "
            "loaded = [m for m in ('authlib', 'joserfc') if m in sys.modules]; "
            "assert not loaded, f'imported at startup: {loaded}'")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, cwd=repo_root)
    assert result.returncode == 0, result.stderr[-2000:]


# ---- the whole sign-in ----

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit

CALLBACK = 'https://claude.ai/api/mcp/auth_callback'


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


def _register(client, name='Claude', redirect_uris=(CALLBACK,)):
    res = client.post('/oauth/register', json={'client_name': name, 'redirect_uris': list(redirect_uris)})
    assert res.status_code == 201, res.json
    return res.json['client_id']


def _authorize_url(client_id, challenge, mcp_url, redirect_uri=CALLBACK, **extra):
    params = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri, 'scope': 'mcp',
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'state': 'xyz', 'resource': mcp_url}
    params.update(extra)
    return '/oauth/authorize?' + urlencode({k: v for k, v in params.items() if v is not None})


GRID = {'perm_monitors': 'read', 'perm_tags': 'read', 'perm_notifications': 'none', 'perm_system': 'read'}


def _approve(client, url, name='Claude web', grid=GRID):
    res = client.post(url, data=dict(grid, name=name, decision='approve'))
    assert res.status_code == 302, res.get_data(as_text=True)[:500]
    return parse_qs(urlsplit(res.location).query)


def _tools(client, access_token):
    res = client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                      content_type='application/json', headers={'Authorization': f'Bearer {access_token}'})
    return res.status_code, ({t['name'] for t in res.json['result']['tools']} if res.status_code == 200 else None)


# Sign-in is https only; the instance's public address (the Base URL), as behind a proxy that ends TLS
BASE = 'https://cd.example.com'
MCP_URL = BASE + '/mcp/v1'


@pytest.fixture()
def logged_in(client):
    from changedetectionio.blueprint.mcp import oauth
    settings = client.application.config['DATASTORE'].data['settings']['application']
    oauth._register_log.clear()
    settings['base_url'] = BASE
    client.application.config['LOGIN_DISABLED'] = True
    yield
    client.application.config['LOGIN_DISABLED'] = False
    settings['base_url'] = ''
    settings.pop('mcp_oauth', None)


def test_sign_in(client, live_server, measure_memory_usage, datastore_path, logged_in):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    mcp_url, base = MCP_URL, BASE
    client_id = _register(client)
    verifier, challenge = _pkce()
    url = _authorize_url(client_id, challenge, mcp_url)

    # The consent screen: who's asking (a DCR name isn't verified), where it sends you back, the grid
    html = client.get(url).get_data(as_text=True)
    assert 'Allow Claude to use changedetection.io?' in html and 'it is not verified' in html
    assert '>claude.ai</code>' in html and 'name="perm_monitors"' in html and 'name="csrf_token"' in html

    # Allowed: back to the assistant with a code, its state, and who issued it (RFC 9207)
    answer = _approve(client, url)
    assert answer['state'] == ['xyz'] and answer['iss'] == [base]
    code = answer['code'][0]

    # The code for tokens, with the PKCE verifier
    token_form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': CALLBACK, 'client_id': client_id,
                  'code_verifier': verifier, 'resource': mcp_url}
    res = client.post('/oauth/token', data=token_form)
    assert res.status_code == 200, res.json
    tokens = res.json
    assert tokens['token_type'].lower() == 'bearer' and tokens['expires_in'] == 3600 and tokens['refresh_token']
    assert res.headers.get('Cache-Control') == 'no-store'
    # Stored hashed, never the tokens themselves
    stored = json.dumps(settings['mcp_oauth'])
    assert tokens['access_token'] not in stored and tokens['refresh_token'] not in stored

    # The token works on /mcp/v1, with the grid picked on the consent screen
    status, tools = _tools(client, tokens['access_token'])
    assert status == 200
    assert 'list_watches' in tools and 'create_watch' not in tools and 'list_notifications' not in tools
    grant = list(settings['mcp_oauth']['grants'].values())[0]
    assert grant['name'] == 'Claude web' and grant['client_name'] == 'Claude' and grant['last_used']

    # A code is used once
    assert client.post('/oauth/token', data=token_form).json['error'] == 'invalid_grant'

    # Refresh: new tokens, and the old refresh and access tokens stop working
    res = client.post('/oauth/token', data={'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'],
                                            'client_id': client_id})
    assert res.status_code == 200, res.json
    fresh = res.json
    assert fresh['refresh_token'] != tokens['refresh_token']
    assert client.post('/oauth/token', data={'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token'],
                                             'client_id': client_id}).json['error'] == 'invalid_grant'
    assert _tools(client, tokens['access_token'])[0] == 401
    assert _tools(client, fresh['access_token'])[0] == 200

    # Only offered with a password: without one the token stops working too
    settings['password'] = False
    assert _tools(client, fresh['access_token'])[0] == 401
    settings['password'] = 'something'
    assert _tools(client, fresh['access_token'])[0] == 200

    # Revoked from the settings (the OAuth sub-tab)
    grant_id = list(settings['mcp_oauth']['grants'])[0]
    res = client.post(url_for('settings.llm.mcp_oauth_revoke', grant_id=grant_id))
    assert res.status_code == 200 and 'Claude web' not in res.json['html']
    assert _tools(client, fresh['access_token'])[0] == 401


def test_sign_in_refused(client, live_server, measure_memory_usage, datastore_path, logged_in):
    mcp_url = MCP_URL
    client_id = _register(client)
    verifier, challenge = _pkce()

    # Denied: back to the assistant with access_denied
    answer = parse_qs(urlsplit(client.post(_authorize_url(client_id, challenge, mcp_url),
                                           data={'decision': 'deny'}).location).query)
    assert answer['error'] == ['access_denied'] and answer['state'] == ['xyz'] and 'iss' in answer

    # Shown here, never redirected: no S256, another resource, an unknown client, a redirect URI it didn't register
    for url, expect in (
            (_authorize_url(client_id, challenge, mcp_url, code_challenge_method='plain'), 'S256'),
            (_authorize_url(client_id, None, mcp_url), 'S256'),
            (_authorize_url(client_id, challenge, 'https://elsewhere.example.com/mcp'), 'only for'),
            (_authorize_url('nobody', challenge, mcp_url), "be used"),
            (_authorize_url(client_id, challenge, mcp_url, redirect_uri='https://attacker.example.com/cb'), "be used")):
        res = client.get(url)
        assert res.status_code == 400 and expect in res.get_data(as_text=True), url

    # A wrong PKCE verifier gets no tokens
    code = _approve(client, _authorize_url(client_id, challenge, mcp_url))['code'][0]
    res = client.post('/oauth/token', data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': CALLBACK,
                                            'client_id': client_id, 'code_verifier': 'x' * 50})
    assert res.status_code == 400 and 'access_token' not in res.json
    # Tokens for another resource aren't issued
    res = client.post('/oauth/token', data={'grant_type': 'authorization_code', 'resource': 'https://elsewhere.example.com/mcp'})
    assert res.json['error'] == 'invalid_target'

    # https only: plain http (other than localhost) is refused, with what to do about it
    settings = client.application.config['DATASTORE'].data['settings']['application']
    settings['base_url'] = 'http://cd.example.com'
    res = client.get(_authorize_url(client_id, challenge, 'http://cd.example.com/mcp/v1'))
    assert res.status_code == 400 and 'Sign-in needs https' in res.get_data(as_text=True)
    assert client.post('/oauth/token', data={'grant_type': 'refresh_token'}).status_code == 400
    settings['base_url'] = BASE

    # Behind the login: logged out, the consent screen sends you to /login first
    client.application.config['LOGIN_DISABLED'] = False
    res = client.get(_authorize_url(client_id, challenge, mcp_url))
    assert res.status_code == 302 and '/login' in res.location


def test_register_limits(client, live_server, measure_memory_usage, datastore_path, logged_in):
    for body, error in (({'redirect_uris': ['http://claude.ai/cb']}, 'invalid_redirect_uri'),
                        ({'redirect_uris': []}, 'invalid_redirect_uri'),
                        ({'redirect_uris': [CALLBACK], 'token_endpoint_auth_method': 'client_secret_basic'}, 'invalid_client_metadata'),
                        ({'redirect_uris': [CALLBACK], 'grant_types': ['client_credentials']}, 'invalid_client_metadata')):
        res = client.post('/oauth/register', json=body)
        assert res.status_code == 400 and res.json['error'] == error, body
    # http is fine on localhost (apps on this computer), and a missing name gets a placeholder
    res = client.post('/oauth/register', json={'redirect_uris': ['http://127.0.0.1:33418/callback']})
    assert res.status_code == 201 and res.json['client_name'] == 'Unnamed assistant'
    # Open to anyone, so a few per address per hour
    for _ in range(20):
        res = client.post('/oauth/register', json={'redirect_uris': [CALLBACK]})
    assert res.status_code == 429
    assert client.post('/oauth/register', data='x' * 6000, content_type='application/json').status_code == 413


def test_cimd_client(client, live_server, measure_memory_usage, datastore_path, logged_in, monkeypatch):
    from changedetectionio.blueprint.mcp.oauth import cimd
    client_id = 'https://chatgpt.com/oauth/client.json'
    redirect = 'https://chatgpt.com/connector_platform_oauth_redirect'
    documents = {client_id: {'client_id': client_id, 'client_name': 'ChatGPT', 'redirect_uris': [redirect]},
                 'https://evil.example.com/client.json': {'client_id': 'https://chatgpt.com/oauth/client.json',
                                                          'client_name': 'ChatGPT', 'redirect_uris': [redirect]}}
    monkeypatch.setattr(cimd, '_fetch_document', lambda url: json.dumps(documents[url]).encode())
    cimd._cache.clear()
    mcp_url = MCP_URL
    verifier, challenge = _pkce()

    # No registration: the client_id is the URL of its metadata, and its real host is shown next to its name
    url = _authorize_url(client_id, challenge, mcp_url, redirect_uri=redirect)
    html = client.get(url).get_data(as_text=True)
    assert 'Allow ChatGPT to use changedetection.io?' in html and 'from chatgpt.com' in html
    code = _approve(client, url)['code'][0]
    res = client.post('/oauth/token', data={'grant_type': 'authorization_code', 'code': code, 'redirect_uri': redirect,
                                            'client_id': client_id, 'code_verifier': verifier})
    assert res.status_code == 200 and _tools(client, res.json['access_token'])[0] == 200

    # A document that names another client_id than its own URL is refused
    res = client.get(_authorize_url('https://evil.example.com/client.json', challenge, mcp_url, redirect_uri=redirect))
    assert res.status_code == 400 and "name its own URL as client_id" in res.get_data(as_text=True)


def test_cimd_url_and_address_rules():
    from changedetectionio.blueprint.mcp.oauth.cimd import CIMDError, is_public_address, validate_client_id_url
    validate_client_id_url('https://chatgpt.com/oauth/client.json')
    for bad in ('http://chatgpt.com/client.json', 'https://chatgpt.com', 'https://chatgpt.com/',
                'https://user:pw@chatgpt.com/c.json', 'https://chatgpt.com/c.json#x', 'https://chatgpt.com/a/../c.json'):
        with pytest.raises(CIMDError):
            validate_client_id_url(bad)
    # SSRF: nothing but public addresses, IPv4-mapped IPv6 included
    for private in ('127.0.0.1', '10.0.0.5', '192.168.1.1', '169.254.169.254', '::1', 'fd00::1', '::ffff:127.0.0.1', '0.0.0.0'):
        assert not is_public_address(private), private
    assert is_public_address('104.18.32.47') and is_public_address('2606:4700::6810:2c2f')


def test_endpoints_called_by_the_assistant_skip_csrf(client, live_server, measure_memory_usage, datastore_path, logged_in):
    # The tests switch CSRF off; the assistant's server posts to /oauth/register and /oauth/token without a CSRF
    # token, so check those really are exempt with it on (and the consent form isn't)
    client.application.config['WTF_CSRF_ENABLED'] = True
    try:
        res = client.post('/oauth/register', json={'client_name': 'Claude', 'redirect_uris': [CALLBACK],
                                                    'grant_types': ['authorization_code', 'refresh_token'],
                                                    'response_types': ['code'], 'token_endpoint_auth_method': 'none'})
        assert res.status_code == 201, res.get_data(as_text=True)[:300]
        res = client.post('/oauth/token', data={'grant_type': 'refresh_token', 'refresh_token': 'x', 'client_id': 'y'})
        assert res.status_code != 400 or res.is_json, "refused by CSRF, not by OAuth"
        verifier, challenge = _pkce()
        res = client.post(_authorize_url(_register(client), challenge, MCP_URL), data=dict(GRID, name='x', decision='approve'))
        assert res.status_code == 400 and 'CSRF' in res.get_data(as_text=True)
    finally:
        client.application.config['WTF_CSRF_ENABLED'] = False


def test_discovery_under_a_sub_path(client, live_server, measure_memory_usage, datastore_path):
    # Installs at / and at a sub-path (site.com/changedetection/) both get found: everything is built from the issuer,
    # which includes the sub-path, and the metadata is also at {issuer}/.well-known/openid-configuration, where clients
    # look when RFC 8414's host-root address (outside the sub-path) doesn't reach the instance
    base = 'http://localhost/changedetection'
    challenge = _ping_at(client, base).headers['WWW-Authenticate']
    assert f'resource_metadata="{base}/.well-known/oauth-protected-resource/mcp/v1"' in challenge
    resource_meta = client.get('/.well-known/oauth-protected-resource/mcp/v1', base_url=base + '/').json
    assert resource_meta == {**resource_meta, 'resource': f'{base}/mcp/v1', 'authorization_servers': [base]}
    meta = client.get('/.well-known/openid-configuration', base_url=base + '/').json
    assert meta['issuer'] == base and meta['authorization_endpoint'] == f'{base}/oauth/authorize'
    assert meta['registration_endpoint'] == f'{base}/oauth/register' and meta['token_endpoint'] == f'{base}/oauth/token'


def _ping_at(client, base):
    return client.post('/mcp/v1', base_url=base + '/', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
                       content_type='application/json')


def test_consent_form_keeps_the_sub_path(client, live_server, measure_memory_usage, datastore_path, logged_in):
    # Behind a proxy at /big-balls/, the consent form must post back under /big-balls/, not to the host root (a 404)
    import re
    client_id = _register(client)
    verifier, challenge = _pkce()
    html = client.get(_authorize_url(client_id, challenge, MCP_URL), base_url='http://localhost/big-balls/').get_data(as_text=True)
    action = re.search(r'<form class="pure-form pure-form-stacked" method="POST" action="([^"]+)"', html).group(1)
    assert action.startswith('/big-balls/oauth/authorize?') and 'code_challenge=' in action
    # And the answer, posted there, still works
    res = client.post(action.replace('&amp;', '&').removeprefix('/big-balls'), data=dict(GRID, name='x', decision='approve'),
                      base_url='http://localhost/big-balls/')
    assert res.status_code == 302 and 'code=' in res.location
