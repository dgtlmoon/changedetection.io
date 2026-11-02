#!/usr/bin/env python3
"""The AI settings pages: /settings/ai/llm and /settings/ai/mcp ("MCP Server" tab), the MCP token, and the
switches that turn MCP off (DISABLE_MCP, LLM_FEATURES_DISABLED)."""
import json

import pytest
from flask import url_for
from .util import delete_all_watches, new_mcp_token


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    """The MCP server is off until the switch on its settings tab is on, these tests are about it being on."""
    client.application.config['DATASTORE'].data['settings']['application']['mcp_enabled'] = True


def _ping(client, token):
    return client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}),
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
    token = new_mcp_token(client)
    mcp_url = url_for('mcp.endpoint', _external=True)

    res = client.get(url_for('settings.llm.mcp_settings_page'))
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    # Its own page, "MCP Server" marked active by the server in the AI pages' switch
    assert (f'<a href="{url_for("settings.llm.mcp_settings_page")}" class="settings-subtab subtab-incoming active" '
            f'aria-current="page">') in html
    assert 'id="mcp"' in html and 'id="ai"' not in html
    assert 'Model Context Protocol' in html
    # The address, click to copy, and the Claude Code command built from it, reading the token from the environment
    assert 'id="mcp-url" class="click-to-copy' in html and f'>{mcp_url}</code>' in html
    assert (f'claude mcp add --transport http changedetection {mcp_url} '
            f'--header &#34;Authorization: Bearer $CDIO_MCP_TOKEN&#34;') in html
    # Tokens are only kept hashed, so the page can never show one
    assert token not in html
    assert f'{mcp_url}?readonly=1' in html
    assert mcp_url.endswith('/mcp/v1'), "the endpoint path is versioned"
    # Never the REST API key
    assert settings['api_access_token'] not in html

    # The token is treated like a password: a warning, and an environment variable for the configs that can use one
    assert 'Treat it like a password.' in html
    assert 'export CDIO_MCP_TOKEN=YOUR_MCP_TOKEN' in html
    import re
    def block(element_id):
        return re.search(rf'<code id="{element_id}"[^>]*>(.*?)</code>', html, re.S).group(1)
    # Claude Code --scope project writes .mcp.json (usually committed): a reference to the variable, never the token
    project = block('mcp-claude-code-project')
    assert '--scope project' in project and '${CDIO_MCP_TOKEN}' in project and token not in project
    # Clients that read environment variables (or prompt for the token) never get the token in their file
    for element_id, reference in (('mcp-cursor', '${env:CDIO_MCP_TOKEN}'), ('mcp-vscode', '${input:cdio-mcp-token}'),
                                  ('mcp-codex', 'bearer_token_env_var = &#34;CDIO_MCP_TOKEN&#34;'),
                                  ('mcp-opencode', '{env:CDIO_MCP_TOKEN}')):
        config = block(element_id)
        assert reference in config and token not in config, element_id
        assert mcp_url in config, element_id
    assert '&#34;password&#34;: true' in block('mcp-vscode')
    assert '[mcp_servers.changedetection]\nurl = ' in block('mcp-codex'), "TOML on separate lines"
    # Each client's own key names: Gemini CLI's httpUrl (url would mean SSE), OpenCode's type remote, Zed's context_servers
    assert '&#34;httpUrl&#34;' in block('mcp-gemini')
    assert '&#34;type&#34;: &#34;remote&#34;' in block('mcp-opencode')
    assert '&#34;context_servers&#34;' in block('mcp-zed')
    assert 'copilot mcp add --transport http' in block('mcp-copilot-cli')
    assert 'mcp-remote' in block('mcp-other')

    # The configured Base URL is the public address when it's set
    settings['base_url'] = 'https://lemonade.example.com/instance-url/'
    try:
        html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
        assert '>https://lemonade.example.com/instance-url/mcp/v1</code>' in html
    finally:
        settings['base_url'] = ''


def test_mcp_on_off_switch(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    settings = datastore.data['settings']['application']
    token = new_mcp_token(client)

    # Off by default: a fresh install has no mcp_enabled at all
    settings.pop('mcp_enabled', None)
    assert _ping(client, token).status_code == 404, "off until switched on, even with the right token"
    html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
    # The switch first in the form, red and saying it's off
    assert 'id="enabled"' in html and 'checked id="enabled"' not in html
    assert html.index('id="enabled"') < html.index('Connect AI assistants with MCP')
    assert '<div class="mcp-power">' in html and 'Everything here can still be set up first.' in html
    # Every sub-tab is there while it's off, so it can all be set up first
    for tab in ('overview', 'connect', 'tokens', 'oauth'):
        assert f'data-stab="{tab}"' in html, tab
    assert 'id="mcp-url"' in html and 'data-mcp-token-add' in html
    assert '<div id="actions">' in html

    # Tokens can be added while it's off, and it stays off
    res = client.post(url_for('settings.llm.mcp_token_add'), data={'name': 'Cursor', 'perm_monitors': 'read',
                                                                 'perm_tags': 'read', 'perm_notifications': 'none',
                                                                 'perm_system': 'read'})
    assert res.status_code == 200 and not settings.get('mcp_enabled')
    assert _ping(client, res.json['token']).status_code == 404

    # Switched on, the token added while it was off works
    res = client.post(url_for('settings.llm.mcp_settings_page'), data={'enabled': 'y'}, follow_redirects=True)
    assert b'MCP server switched on.' in res.data
    assert settings['mcp_enabled'] is True and _ping(client, token).status_code == 200
    assert b'checked id="enabled"' in res.data and b'<div class="mcp-power on">' in res.data

    # Switched off again: refused before auth, so a wrong token gets the same answer
    res = client.post(url_for('settings.llm.mcp_settings_page'), data={}, follow_redirects=True)
    assert b'MCP server switched off.' in res.data
    assert settings['mcp_enabled'] is False
    assert _ping(client, token).status_code == 404 and _ping(client, 'wrong').status_code == 404
    assert 'switched off' in _ping(client, token).json['error']

    settings['mcp_enabled'] = True


def test_mcp_switched_off(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    token = new_mcp_token(client)

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
    assert client.get(url_for('settings.llm.mcp_tokens_list')).status_code == 404
    assert client.post(url_for('settings.llm.mcp_token_add'), data={'name': 'x'}).status_code == 404


def _rpc(client, token, method, params=None):
    return client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def _tool_names(client, token, readonly=False):
    res = client.post('/mcp/v1' + ('?readonly=1' if readonly else ''), content_type='application/json',
                      data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                      headers={'Authorization': f'Bearer {token}'})
    return {t['name'] for t in res.json['result']['tools']}


GRID = {'perm_monitors': 'write', 'perm_tags': 'write', 'perm_notifications': 'read', 'perm_system': 'read'}


def test_mcp_access_tokens(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    settings = datastore.data['settings']['application']
    settings.pop('mcp_tokens', None)
    uuid = datastore.add_watch(url='https://example.com/keep-me', extras={'paused': True})

    # None yet, and the overlay (outside the page's form, nested forms are invalid) with the defaults ticked
    html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
    # No tokens: a call to action that opens the add overlay, from the list and from Overview
    assert 'Add your first access token' in html and 'class="mcp-token-cta" data-mcp-token-add' in html
    assert 'Get started' in html and 'data-stab-goto="tokens" data-mcp-token-add>+ Add access token' in html
    page_form = html.split(f'action="{url_for("settings.llm.mcp_settings_page")}" method="POST">')[1].split('</form>')[0]
    assert '<form ' not in page_form and 'name="perm_monitors"' not in page_form
    assert '<dialog id="mcp-token-dialog"' in html
    for area, level in (('monitors', 'write'), ('tags', 'write'), ('notifications', 'read'), ('system', 'read')):
        assert f'checked id="perm_{area}-' in html and f'name="perm_{area}" type="radio" value="{level}"' in html
    assert 'name="perm_system" type="radio" value="write"' not in html

    # Added with ajax: the token comes back this once, with the re-rendered list
    res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name='Claude Code, laptop'))
    assert res.status_code == 200
    token, token_id = res.json['token'], res.json['id']
    assert token.startswith('cdio_mcp_') and 'Claude Code, laptop' in res.json['html']
    assert token not in res.json['html'] and token[:13] in res.json['html']
    assert 'Never used' in res.json['html']
    assert 'Monitors <strong>Write</strong>' in res.json['html'] and 'Notifications <strong>Read</strong>' in res.json['html']
    assert token not in json.dumps(settings['mcp_tokens']), "stored hashed"
    # Overview's status comes back too, so it doesn't go stale without a reload: the token, no "Get started" (MCP is on)
    assert 'Claude Code, laptop' in res.json['overview_html'] and 'Get started' not in res.json['overview_html']
    defaults = _tool_names(client, token)
    assert {'delete_watch', 'create_tag', 'list_notifications', 'get_system_info'} <= defaults
    assert 'add_notification' not in defaults
    # The list on its own (the same as after each change) and on the page, now with when it was last used
    listed = client.get(url_for('settings.llm.mcp_tokens_list')).get_data(as_text=True)
    assert 'Claude Code, laptop' in listed and 'Last used' in listed and token not in listed

    # Mistakes come back as errors for the overlay, nothing saved
    res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name=''))
    assert res.status_code == 400 and 'name' in res.json['errors']
    res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name='x', perm_monitors='admin'))
    assert res.status_code == 400 and 'perm_monitors' in res.json['errors']
    res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name='x', perm_system='write'))
    assert res.status_code == 400 and len(settings['mcp_tokens']) == 1

    # Edited to everything read: only the tools that change nothing, and the assistant is told why
    res = client.post(url_for('settings.llm.mcp_token_update', token_id=token_id),
                      data={'name': 'Claude Code', 'perm_monitors': 'read', 'perm_tags': 'read',
                            'perm_notifications': 'read', 'perm_system': 'read'})
    assert res.status_code == 200 and 'Claude Code' in res.json['html'] and 'token' not in res.json
    tools = _tool_names(client, token)
    assert 'delete_watch' not in tools and 'create_tag' not in tools and 'list_watches' in tools
    res = _rpc(client, token, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                             'clientInfo': {'name': 'test', 'version': '1'}})
    assert 'read-only' in res.json['result']['instructions']
    # A client with the old tool list cached still can't change anything, it gets an error it can pass on
    result = _rpc(client, token, 'tools/call', {'name': 'delete_watch', 'arguments': {'watch': uuid}}).json['result']
    assert result['isError'] is True
    text = result['content'][0]['text']
    assert "('Claude Code') has 'read' access to monitors" in text and 'Access tokens' in text
    assert uuid in datastore.data['watching']
    assert _rpc(client, token, 'tools/call', {'name': 'list_watches', 'arguments': {}}).json['result']['isError'] is False

    # None: the row's tools aren't offered at all, not even to read; each token has its own grid
    res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name='Tags off', perm_tags='none', perm_system='none'))
    other = res.json['token']
    tools = _tool_names(client, other)
    assert not {'list_tags', 'create_tag', 'delete_tag', 'get_system_info'} & tools and 'create_watch' in tools
    result = _rpc(client, other, 'tools/call', {'name': 'list_tags', 'arguments': {}}).json['result']
    assert result['isError'] is True and "has 'none' access to tags" in result['content'][0]['text']
    assert 'list_tags' in _tool_names(client, token), "the first token is unchanged"

    # System info can't be write, even by hand in the datastore; ?readonly=1 caps every row at read for one connector
    settings['mcp_tokens'][token_id]['permissions'] = {'system': 'write'}
    assert 'get_system_info' in _tool_names(client, token)
    readonly = _tool_names(client, other, readonly=True)
    assert 'list_watches' in readonly and 'create_watch' not in readonly

    # Revoked: refused at once, the other token keeps working; unknown ids are a 404
    res = client.post(url_for('settings.llm.mcp_token_revoke', token_id=token_id))
    assert res.status_code == 200 and 'Claude Code' not in res.json['html'] and 'Tags off' in res.json['html']
    assert 'Claude Code' not in res.json['overview_html'] and 'Tags off' in res.json['overview_html']
    assert _ping(client, token).status_code == 403 and _ping(client, other).status_code == 200
    assert client.post(url_for('settings.llm.mcp_token_revoke', token_id=token_id)).status_code == 404
    assert client.post(url_for('settings.llm.mcp_token_update', token_id='nope'), data=dict(GRID, name='x')).status_code == 404
    # The last one revoked: "Get started" is back on Overview straight away
    res = client.post(url_for('settings.llm.mcp_token_revoke', token_id=list(settings['mcp_tokens'])[0]))
    assert 'Get started' in res.json['overview_html'] and 'Add your first access token' in res.json['html']

    settings.pop('mcp_tokens', None)
    delete_all_watches(client)


def test_mcp_types_imported_lazily():
    # mcp-types costs ~15MB, it must not be loaded by starting the app, only by the first authenticated /mcp request
    import os
    import subprocess
    import sys
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    code = ("import sys, changedetectionio.flask_app, changedetectionio.blueprint.mcp, "
            "changedetectionio.blueprint.mcp.tools, changedetectionio.blueprint.settings.llm; "
            "assert 'mcp_types' not in sys.modules, 'mcp_types imported at startup'")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, cwd=repo_root)
    assert result.returncode == 0, result.stderr[-2000:]


def test_ai_pages_settings_tab_row(client, live_server, measure_memory_usage, datastore_path):
    # The AI pages look like a tab of /settings: the same tab row (settings-tabs.html), "AI / LLM / MCP" active,
    # and its other tabs link back to /settings#<tab>
    settings_page = url_for('settings.settings_page')
    llm_page = url_for('settings.llm.llm_settings_page')
    mcp_page = url_for('settings.llm.mcp_settings_page')
    ai_tab = f'<a href="{llm_page}">AI / LLM / MCP</a>'

    html = client.get(settings_page).get_data(as_text=True)
    # On /settings the tabs stay in-page #anchors for tabs.js, the AI tab is a link and not active
    assert '<li class="tab"><a href="#fetching">' in html and f'<li class="tab">{ai_tab}</li>' in html
    assert f'href="{url_for("backups.create")}"' in html

    for page, active_switch, direction in ((llm_page, llm_page, 'outgoing'), (mcp_page, mcp_page, 'incoming')):
        html = client.get(page).get_data(as_text=True)
        assert f'<li class="tab active">{ai_tab}</li>' in html, page
        assert html.count('<li class="tab active">') == 1, page
        for anchor in ('general', 'fetching', 'filters', 'ui-options', 'api', 'rss', 'timedate', 'proxies', 'info'):
            assert f'<li class="tab"><a href="{settings_page}#{anchor}">' in html, (page, anchor)
        assert f'href="{url_for("backups.create")}"' in html
        assert f'<a href="{active_switch}" class="settings-subtab subtab-{direction} active" aria-current="page">' in html, page


def test_ai_settings_csrf(client, live_server, measure_memory_usage, datastore_path):
    # The test config switches CSRF off, so prove the AI settings pages are protected with it switched back on
    import re
    app = client.application
    settings = app.config['DATASTORE'].data['settings']['application']
    settings.pop('mcp_tokens', None)
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        # Every route that changes something refuses a POST without the CSRF token (a cross-site form post)
        for endpoint in ('settings.llm.llm_settings_page', 'settings.llm.mcp_settings_page',
                         'settings.llm.mcp_token_add', 'settings.llm.llm_test', 'settings.llm.llm_clear',
                         'settings.llm.llm_clear_summary_cache'):
            res = client.post(url_for(endpoint), data=dict(GRID, name='cross-site'))
            assert res.status_code == 400, f"{endpoint} accepted a POST without a CSRF token ({res.status_code})"
        assert not settings.get('mcp_tokens')

        # The token in the page's form is accepted, for Save and for the "Regenerate MCP token" formaction button
        html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        res = client.post(url_for('settings.llm.mcp_settings_page'), data={'csrf_token': csrf_token, 'enabled': 'y'})
        assert res.status_code == 302
        # The overlay's ajax calls send it in the X-CSRFToken header (csrf.js)
        res = client.post(url_for('settings.llm.mcp_token_add'), data=dict(GRID, name='ajax'), headers={'X-CSRFToken': csrf_token})
        assert res.status_code == 200 and len(settings['mcp_tokens']) == 1
        token_id = res.json['id']
        assert client.post(url_for('settings.llm.mcp_token_revoke', token_id=token_id)).status_code == 400
        res = client.post(url_for('settings.llm.mcp_token_revoke', token_id=token_id), headers={'X-CSRFToken': csrf_token})
        assert res.status_code == 200 and not settings['mcp_tokens']
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
        settings.pop('mcp_tokens', None)
