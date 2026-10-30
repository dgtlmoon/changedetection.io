#!/usr/bin/env python3
"""The AI settings pages: /settings/ai/llm and /settings/ai/mcp ("MCP Server" tab), the MCP token, and the
switches that turn MCP off (DISABLE_MCP, LLM_FEATURES_DISABLED)."""
import json

from flask import url_for


def _ping(client, token):
    return client.post('/mcp', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def test_ai_settings_urls(client, live_server, measure_memory_usage, datastore_path):
    llm_page = url_for('settings.llm.llm_settings_page')
    mcp_page = url_for('settings.llm.mcp_settings_page')
    assert llm_page.endswith('/settings/ai/llm') and mcp_page.endswith('/settings/ai/mcp')

    # /settings/ai opens the AI / LLM tab, and the old /settings/llm address still works
    for old in ('/settings/ai', '/settings/llm'):
        res = client.get(old)
        assert res.status_code == 302 and res.location.endswith('/settings/ai/llm'), old


def test_mcp_settings_page(client, live_server, measure_memory_usage, datastore_path):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    token = settings['mcp_access_token']
    mcp_url = url_for('mcp.endpoint', _external=True)

    res = client.get(url_for('settings.llm.mcp_settings_page'))
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    # Its own page, the MCP tab marked active by the server
    assert f'<li class="tab active"><a href="{url_for("settings.llm.mcp_settings_page")}">' in html
    assert 'id="mcp"' in html and 'id="ai"' not in html
    assert 'Model Context Protocol' in html
    # The address and the token, click to copy, and the Claude Code command built from them
    assert f'id="mcp-url" class="click-to-copy"' in html and f'>{mcp_url}</code>' in html
    assert f'>{token}</code>' in html
    assert (f'claude mcp add --transport http changedetection {mcp_url} '
            f'--header &#34;Authorization: Bearer {token}&#34;') in html
    assert f'{mcp_url}?readonly=1' in html
    # Never the REST API key
    assert settings['api_access_token'] not in html

    # The configured Base URL is the public address when it's set
    settings['base_url'] = 'https://lemonade.example.com/instance-url/'
    try:
        html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
        assert '>https://lemonade.example.com/instance-url/mcp</code>' in html
    finally:
        settings['base_url'] = ''


def test_mcp_token_regenerate(client, live_server, measure_memory_usage, datastore_path):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    old_token = settings['mcp_access_token']
    assert _ping(client, old_token).status_code == 200

    res = client.post(url_for('settings.llm.mcp_reset_token'), follow_redirects=True)
    assert res.status_code == 200
    assert b'MCP access token regenerated' in res.data
    new_token = settings['mcp_access_token']
    assert new_token and new_token != old_token
    assert new_token.encode() in res.data, "back on the MCP tab, showing the new token"

    # The old token stops working straight away
    assert _ping(client, old_token).status_code == 403
    assert _ping(client, new_token).status_code == 200


def test_mcp_switched_off(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    token = client.application.config['DATASTORE'].data['settings']['application']['mcp_access_token']

    # DISABLE_MCP: /mcp is refused (and not registered at all when set at startup), the tab says so
    monkeypatch.setenv('DISABLE_MCP', 'true')
    assert _ping(client, token).status_code == 404
    res = client.get(url_for('settings.llm.mcp_settings_page'))
    assert res.status_code == 200
    assert b'The MCP server is switched off on this installation.' in res.data
    assert token.encode() not in res.data
    monkeypatch.delenv('DISABLE_MCP')
    assert _ping(client, token).status_code == 200

    # LLM_FEATURES_DISABLED switches every AI feature off, MCP and both settings pages included
    monkeypatch.setenv('LLM_FEATURES_DISABLED', 'true')
    assert _ping(client, token).status_code == 404
    assert client.get(url_for('settings.llm.mcp_settings_page')).status_code == 404
    assert client.get(url_for('settings.llm.llm_settings_page')).status_code == 404
