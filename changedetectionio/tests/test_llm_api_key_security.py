#!/usr/bin/env python3
"""
Security tests: LLM API key must never appear in any API response.

The LLM API key is a secret credential stored in
datastore.data['settings']['application']['llm']['api_key'].
It must never be leaked through any API endpoint — watch GET/list,
tag GET/list, system-info, notifications — even when the calling client
has a valid API token (which is a different kind of credential).

These tests set a recognisable fake key and then exhaustively check every
API endpoint's response body for the key string.
"""

import json

from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches

CANARY_KEY = 'sk-CANARY-SECRET-DO-NOT-EXPOSE-12345'


def _configure_llm(datastore, api_key=CANARY_KEY):
    """Inject a recognisable API key into the datastore LLM settings."""
    app = datastore.data['settings']['application']
    if 'llm' not in app:
        app['llm'] = {}
    app['llm'].update({
        'model': 'gpt-4o-mini',
        'api_key': api_key,
    })


def _api_token(client):
    return client.application.config.get('DATASTORE').data['settings']['application'].get('api_access_token')


def _key_in_response(response, key=CANARY_KEY) -> bool:
    """Return True if the canary key appears anywhere in the response body."""
    body = response.data.decode('utf-8', errors='replace')
    return key in body


# ---------------------------------------------------------------------------
# Watch endpoints
# ---------------------------------------------------------------------------

def test_watch_get_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/watch/<uuid> must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )
    assert res.status_code == 201
    uuid = res.json.get('uuid')

    res = client.get(
        f'/api/v1/watch/{uuid}',
        headers={'x-api-key': api_token},
    )
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/watch/<uuid> response"

    delete_all_watches(client)


def test_watch_list_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/watches must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )

    res = client.get('/api/v1/watch', headers={'x-api-key': api_token})
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/watch (list) response"

    delete_all_watches(client)


def test_watch_put_response_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """PUT /api/v1/watch/<uuid> response must not echo back the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )
    assert res.status_code == 201
    uuid = res.json.get('uuid')

    res = client.put(
        f'/api/v1/watch/{uuid}',
        headers={'x-api-key': api_token, 'content-type': 'application/json'},
        data=json.dumps({'url': test_url, 'title': 'updated'}),
    )
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in PUT /api/v1/watch/<uuid> response"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Tag endpoints
# ---------------------------------------------------------------------------

def test_tag_get_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/tag/<uuid> must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    tag_uuid = ds.add_tag('security-test-tag')

    res = client.get(
        f'/api/v1/tag/{tag_uuid}',
        headers={'x-api-key': api_token},
    )
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/tag/<uuid> response"

    delete_all_watches(client)


def test_tag_list_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/tags must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    res = client.get('/api/v1/tags', headers={'x-api-key': api_token})
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/tags response"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# System / global endpoints
# ---------------------------------------------------------------------------

def test_system_info_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/systeminfo must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    res = client.get('/api/v1/systeminfo', headers={'x-api-key': api_token})
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/systeminfo response"

    delete_all_watches(client)


def test_notifications_api_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET/POST/PUT /api/v1/notifications must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    # GET
    res = client.get('/api/v1/notifications', headers={'x-api-key': api_token})
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/notifications response"

    # POST — add a notification URL; response must not echo back LLM config
    res = client.post(
        '/api/v1/notifications',
        headers={'x-api-key': api_token, 'content-type': 'application/json'},
        data=json.dumps({'notification_urls': ['json://localhost/']}),
    )
    assert res.status_code in (200, 201, 400)  # 400 if URL invalid on server; still no key
    assert not _key_in_response(res), \
        "LLM API key leaked in POST /api/v1/notifications response"

    # PUT — replace notification URLs; response must not include LLM config
    res = client.put(
        '/api/v1/notifications',
        headers={'x-api-key': api_token, 'content-type': 'application/json'},
        data=json.dumps({'notification_urls': ['json://localhost/']}),
    )
    assert res.status_code in (200, 201, 400)
    assert not _key_in_response(res), \
        "LLM API key leaked in PUT /api/v1/notifications response"

    delete_all_watches(client)


def test_search_api_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """GET /api/v1/search must not contain the LLM API key."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )

    res = client.get('/api/v1/search?q=endpoint', headers={'x-api-key': api_token})
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/search response"

    delete_all_watches(client)


def test_openapi_spec_does_not_expose_llm_api_key(
        client, live_server, measure_memory_usage, datastore_path):
    """
    GET /api/v1/full-spec returns the static OpenAPI schema YAML.
    It must not embed any runtime secrets (LLM API key).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    # Spec endpoint has no auth requirement, but test with and without key
    res = client.get('/api/v1/full-spec')
    assert res.status_code == 200
    assert not _key_in_response(res), \
        "LLM API key leaked in GET /api/v1/full-spec response"

    delete_all_watches(client)


def test_no_api_settings_endpoint_exists(
        client, live_server, measure_memory_usage, datastore_path):
    """
    There is currently no /api/v1/settings endpoint.
    If one is added in the future it must be covered by its own
    security tests before reaching production.
    This test acts as a canary — it should FAIL if a settings endpoint
    is accidentally wired up without review.
    """
    api_token = _api_token(client)

    # GET and POST to /api/v1/settings must not succeed — no settings endpoint exists.
    # 404 = route not found; 405 = route exists for some methods but not this one.
    # Either means there is no working read/write settings endpoint.
    # A 200/201/400 would indicate a real endpoint was wired up.
    res_get = client.get('/api/v1/settings', headers={'x-api-key': api_token})
    assert res_get.status_code in (404, 405), \
        (f"Unexpected /api/v1/settings GET returned {res_get.status_code}. "
         "A settings endpoint must have explicit LLM key security tests before shipping.")

    res_post = client.post(
        '/api/v1/settings',
        headers={'x-api-key': api_token, 'content-type': 'application/json'},
        data=json.dumps({}),
    )
    assert res_post.status_code in (404, 405), \
        (f"Unexpected /api/v1/settings POST returned {res_post.status_code}. "
         "A settings endpoint must have explicit LLM key security tests before shipping.")

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# Settings HTML page — key must not appear in the form source HTML
# ---------------------------------------------------------------------------

def test_settings_page_does_not_render_llm_api_key_in_plaintext(
        client, live_server, measure_memory_usage, datastore_path):
    """
    The settings page renders the API key form.  Because the field uses
    PasswordField, WTForms must NOT embed the current key value in the HTML
    (PasswordField intentionally omits the value attribute for security).
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)

    res = client.get(url_for('settings.settings_page'))
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')
    assert CANARY_KEY not in body, \
        "LLM API key appeared in plaintext in the settings page HTML source. " \
        "The llm_api_key field must be a PasswordField so the value is never rendered."


def test_settings_form_preserves_api_key_when_submitted_blank(
        client, live_server, measure_memory_usage, datastore_path):
    """
    When the settings form is saved with an empty llm_api_key (which happens
    every time because PasswordField never pre-populates), the existing key
    must be preserved rather than cleared.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds, api_key='sk-should-be-kept')

    res = client.post(
        url_for('settings.settings_page'),
        data={
            'llm-model': 'gpt-4o',
            'llm-api_key': '',           # blank — PasswordField behaviour
            'llm-api_base': '',
            'application-pager_size': '50',
            'application-notification_format': 'System default',
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )
    assert res.status_code == 200

    saved_key = ds.data['settings']['application'].get('llm', {}).get('api_key', '')
    assert saved_key == 'sk-should-be-kept', \
        f"Blank PasswordField submission must not clear the existing API key (got '{saved_key}')"

    delete_all_watches(client)


# ---------------------------------------------------------------------------
# SSRF — api_base must reject private/loopback/reserved hosts (GHSA-jrxm-qjfh-g54f)
# ---------------------------------------------------------------------------

# Hosts that is_private_hostname() must classify as restricted.
# 169.254.169.254 is the cloud metadata service (AWS/GCP IMDSv1).
_SSRF_PRIVATE_HOSTS = [
    'http://127.0.0.1:6379',
    'http://localhost:11434',
    'http://10.0.0.5:8080',
    'http://192.168.1.1',
    'http://169.254.169.254',
]


def test_llm_models_endpoint_blocks_private_api_base(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """GET /settings/llm/models must refuse api_base pointing at private/loopback
    hosts and must never reach litellm."""
    # Default state — protection ON
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)

    for bad in _SSRF_PRIVATE_HOSTS:
        res = client.get(
            url_for('settings.llm.llm_get_models'),
            query_string={'provider': 'openai_compatible', 'api_base': bad},
        )
        assert res.status_code == 400, \
            f"api_base={bad!r} should have been rejected by SSRF guard"
        body = res.get_json()
        assert body['models'] == []
        assert 'ALLOW_IANA_RESTRICTED_ADDRESSES' in body['error'], \
            f"Error message should mention the env-var bypass: {body['error']!r}"
        # The raw attacker-controlled api_base must never be reflected back
        # (avoids XSS when JS renders the error into the DOM).
        assert bad not in body['error']


def test_llm_test_endpoint_blocks_private_api_base(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """GET /settings/llm/test must refuse api_base pointing at private/loopback
    hosts and must never reach litellm.completion()."""
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)

    for bad in _SSRF_PRIVATE_HOSTS:
        res = client.get(
            url_for('settings.llm.llm_test'),
            query_string={'model': 'openai/gpt-4', 'api_base': bad},
        )
        assert res.status_code == 400, \
            f"api_base={bad!r} should have been rejected by SSRF guard"
        body = res.get_json()
        assert body['ok'] is False
        assert 'ALLOW_IANA_RESTRICTED_ADDRESSES' in body['error']
        assert bad not in body['error']


def test_llm_endpoints_allow_api_base_when_iana_bypass_enabled(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """When ALLOW_IANA_RESTRICTED_ADDRESSES=true the SSRF guard is bypassed so
    operators can intentionally point at a local Ollama / vLLM endpoint.
    We patch litellm so the test doesn't actually need a live model server —
    we only need to confirm the guard didn't short-circuit."""
    monkeypatch.setenv('ALLOW_IANA_RESTRICTED_ADDRESSES', 'true')

    # Stub get_valid_models so the call returns successfully without network.
    import litellm
    monkeypatch.setattr(litellm, 'get_valid_models',
                        lambda **kwargs: ['llama3.2'])

    # Supply api_key explicitly so we aren't tripped by the credential-exfil
    # guard (which refuses to substitute the stored key for a non-stored api_base).
    res = client.get(
        url_for('settings.llm.llm_get_models'),
        query_string={'provider': 'openai_compatible',
                      'api_base': 'http://127.0.0.1:11434',
                      'api_key': 'sk-test-explicit'},
    )
    assert res.status_code == 200, \
        "With ALLOW_IANA_RESTRICTED_ADDRESSES=true, private api_base must be allowed"
    body = res.get_json()
    assert body['error'] is None
    assert body['models'], "Stubbed model list should be returned"


def test_settings_form_rejects_private_api_base(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The globalSettingsLLMForm validator must block private api_base values
    when ALLOW_IANA_RESTRICTED_ADDRESSES is not set, and must NOT persist them
    to the datastore."""
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)

    ds = client.application.config.get('DATASTORE')
    # Make sure no stale api_base exists from previous tests.
    ds.data['settings']['application'].pop('llm', None)

    res = client.post(
        url_for('settings.settings_page'),
        data={
            'llm-model':    'gpt-4o',
            'llm-api_key':  '',
            'llm-api_base': 'http://127.0.0.1:11434',
            'application-pager_size': '50',
            'application-notification_format': 'System default',
            'requests-time_between_check-days': '0',
            'requests-time_between_check-hours': '0',
            'requests-time_between_check-minutes': '5',
            'requests-time_between_check-seconds': '0',
            'requests-time_between_check-weeks': '0',
            'requests-workers': '10',
            'requests-timeout': '60',
        },
        follow_redirects=True,
    )
    # Form re-renders with the validation error — page itself returns 200.
    assert res.status_code == 200
    body = res.data.decode('utf-8', errors='replace')
    assert 'ALLOW_IANA_RESTRICTED_ADDRESSES' in body, \
        "Settings page should surface the SSRF guard's bypass-env-var hint"

    saved = ds.data['settings']['application'].get('llm', {}).get('api_base', '')
    assert saved != 'http://127.0.0.1:11434', \
        f"Private api_base must not have been persisted (got {saved!r})"


# ---------------------------------------------------------------------------
# Credential exfiltration — stored api_key must NOT be auto-substituted when
# the caller points api_base at a different (potentially attacker-controlled)
# endpoint. GHSA-g36r-fm2p-87xm.
# ---------------------------------------------------------------------------

def test_llm_models_refuses_to_leak_stored_key_to_different_api_base(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """If the request supplies an api_base that differs from the saved one but
    omits api_key, the endpoint must refuse — otherwise CSRF can ship the
    stored Authorization: Bearer <key> to an attacker-controlled URL."""
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)   # stores CANARY_KEY, leaves api_base unset

    # Patch litellm.get_valid_models so that if the guard ever lets us through
    # we'd see it called — and we can assert it wasn't.
    import litellm
    calls = []
    monkeypatch.setattr(litellm, 'get_valid_models',
                        lambda **kwargs: calls.append(kwargs) or [])

    res = client.get(
        url_for('settings.llm.llm_get_models'),
        query_string={
            'provider': 'openai',
            'api_base': 'https://attacker.example/v1',
            # api_key intentionally omitted — this is the CSRF case
        },
    )
    assert res.status_code == 400, \
        "Endpoint should refuse to substitute stored key to a mismatched api_base"
    body = res.get_json()
    assert 'api_key' in body['error'], \
        f"Error should call out that api_key is required: {body['error']!r}"
    assert calls == [], "litellm must not have been invoked at all"


def test_llm_test_refuses_to_leak_stored_key_to_different_api_base(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Same guard on /settings/llm/test — attacker-supplied api_base + missing
    api_key must not result in the stored key being sent to that URL."""
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)   # stores CANARY_KEY, no stored api_base

    calls = []
    # Patch the completion wrapper so we'd notice if litellm were invoked.
    import changedetectionio.llm.client as llm_client
    monkeypatch.setattr(llm_client, 'completion',
                        lambda **kw: calls.append(kw) or ('', 0, 0, 0))

    res = client.get(
        url_for('settings.llm.llm_test'),
        query_string={
            'model': 'gpt-4o-mini',
            'api_base': 'https://attacker.example/v1',
            # api_key intentionally omitted
        },
    )
    assert res.status_code == 400
    body = res.get_json()
    assert body['ok'] is False
    assert 'api_key' in body['error']
    assert calls == [], "completion() must not have been invoked"


def test_llm_models_allows_stored_key_when_api_base_matches_saved(
        client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Regression: the legit UI flow (test saved config without retyping the key)
    must still work — i.e. when request api_base matches the stored api_base,
    the stored key IS substituted."""
    monkeypatch.delenv('ALLOW_IANA_RESTRICTED_ADDRESSES', raising=False)
    monkeypatch.setenv('ALLOW_IANA_RESTRICTED_ADDRESSES', 'true')  # so localhost passes SSRF
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    ds.data['settings']['application']['llm']['api_base'] = 'http://localhost:11434'

    received = []
    import litellm
    monkeypatch.setattr(litellm, 'get_valid_models',
                        lambda **kwargs: (received.append(kwargs), ['llama3.2'])[1])

    res = client.get(
        url_for('settings.llm.llm_get_models'),
        query_string={
            'provider': 'openai_compatible',
            'api_base': 'http://localhost:11434',  # matches saved
            # api_key omitted — should fall back to stored CANARY_KEY
        },
    )
    assert res.status_code == 200, res.get_json()
    assert received and received[0].get('api_key') == CANARY_KEY, \
        "When api_base matches saved, the stored api_key should be used"


# ---------------------------------------------------------------------------
# CSRF — /clear and /clear-summary-cache must not mutate state on GET
# (GHSA-g36r-fm2p-87xm). The <img src=...> CSRF vector relies on GET firing the
# mutation; the production guard is "POST only + Flask-WTF CSRF token". The
# test config disables WTF_CSRF_ENABLED, so we verify the GET vector by
# asserting the mutation didn't happen, and verify POST routing by exercising
# the legit confirm-then-POST flow.
#
# NB: the app registers a catch-all '/<path:filename>' static route, which
# intercepts any GET that isn't claimed by a method-matching rule and returns
# 404 — so we can't simply assert on status code. The behaviour test below is
# the actual security property.
# ---------------------------------------------------------------------------

def test_llm_clear_get_does_not_wipe_config(
        client, live_server, measure_memory_usage, datastore_path):
    """The CSRF surface is GET → mutation. After this fix the endpoint is
    POST-only, so a GET must leave LLM config intact."""
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    assert ds.data['settings']['application'].get('llm', {}).get('api_key') == CANARY_KEY

    client.get(url_for('settings.llm.llm_clear'))

    # Mutation must not have happened — that's what defeats <img src=...> CSRF.
    assert ds.data['settings']['application'].get('llm', {}).get('api_key') == CANARY_KEY, \
        "GET /settings/llm/clear must not wipe LLM config (CSRF guard)"


def test_llm_clear_summary_cache_get_does_not_wipe_cache(
        client, live_server, measure_memory_usage, datastore_path):
    """Same property for the cache wipe endpoint — GET must not delete the
    change-summary-*.txt files the endpoint targets. To exercise the actual
    deletion path we have to create a real watch (so a real data_dir exists)
    and drop a real change-summary-*.txt inside it. POST should remove it;
    GET must not."""
    import os
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    api_token = _api_token(client)

    # Create a real watch — required to exercise llm_clear_summary_cache's
    # iteration over datastore.data['watching'].values().
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        '/api/v1/watch',
        data=json.dumps({'url': test_url}),
        headers={'content-type': 'application/json', 'x-api-key': api_token},
        follow_redirects=True,
    )
    assert res.status_code == 201
    uuid = res.json.get('uuid')

    watch = ds.data['watching'][uuid]
    data_dir = watch.data_dir
    assert data_dir, "Watch must have a data_dir for this test to be meaningful"
    os.makedirs(data_dir, exist_ok=True)

    summary_file = os.path.join(data_dir, 'change-summary-csrf-canary.txt')
    with open(summary_file, 'w') as f:
        f.write('do-not-delete-via-GET')

    # GET must NOT trigger the wipe — this is the CSRF surface that was open
    # via <img src="/settings/llm/clear-summary-cache">.
    client.get(url_for('settings.llm.llm_clear_summary_cache'))
    assert os.path.exists(summary_file), \
        "GET on /settings/llm/clear-summary-cache must not invoke the cache wipe"

    # Sanity check: POST does remove it — confirms our test actually exercises
    # the deletion path the GET test is guarding against.
    client.post(url_for('settings.llm.llm_clear_summary_cache'))
    assert not os.path.exists(summary_file), \
        "POST on /settings/llm/clear-summary-cache should remove change-summary-*.txt"

    delete_all_watches(client)


def test_llm_clear_via_post_still_works(
        client, live_server, measure_memory_usage, datastore_path):
    """Confirm the legit confirm-then-POST flow wipes the provider credentials.

    Post-LLMSettings: /llm/clear strips only the connection fields (model, api_key,
    api_base, provider_kind, local_token_multiplier). User-set toggles, the global
    summary prompt, monthly budgets, and system token counters survive. This matches
    the settings-page "empty model" save semantic and the LLMSettings.CONNECTION_FIELDS
    grouping — see PYDANTIC_MIGRATION.md.
    """
    ds = client.application.config.get('DATASTORE')
    _configure_llm(ds)
    assert ds.data['settings']['application'].get('llm', {}).get('api_key') == CANARY_KEY

    res = client.post(url_for('settings.llm.llm_clear'), follow_redirects=True)
    assert res.status_code == 200

    # The api_key must be gone (this is what the test really cares about).
    llm = ds.data['settings']['application'].get('llm') or {}
    assert 'api_key' not in llm, f"api_key should have been wiped, got: {llm!r}"
    assert 'model' not in llm
    assert 'api_base' not in llm
