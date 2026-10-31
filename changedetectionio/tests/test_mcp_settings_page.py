#!/usr/bin/env python3
"""The AI settings pages: /settings/ai/llm and /settings/ai/mcp ("MCP Server" tab), the MCP token, and the
switches that turn MCP off (DISABLE_MCP, LLM_FEATURES_DISABLED)."""
import json

from flask import url_for
from .util import delete_all_watches


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
    # Its own page, "MCP Server" marked active by the server in the AI pages' switch
    assert (f'<a href="{url_for("settings.llm.mcp_settings_page")}" class="settings-subtab active" '
            f'aria-current="page">') in html
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


def _rpc(client, token, method, params=None):
    return client.post('/mcp', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def test_mcp_read_only_switch(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    token = datastore.data['settings']['application']['mcp_access_token']
    uuid = datastore.add_watch(url='https://example.com/keep-me', extras={'paused': True})
    all_tools = {t['name'] for t in _rpc(client, token, 'tools/list').json['result']['tools']}
    assert 'delete_watch' in all_tools

    # One form for the page with the usual Save button at the bottom, the token reset posts elsewhere via formaction
    html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
    page_form = html.split(f'action="{url_for("settings.llm.mcp_settings_page")}" method="POST">')[1].split('</form>')[0]
    assert '<form ' not in page_form and 'id="read_only"' in page_form and '<div id="actions">' in page_form
    assert '<div id="actions">' in html and 'class="pure-button pure-button-primary"' in html
    assert html.index('id="read_only"') < html.index('<div id="actions">')
    assert f'formaction="{url_for("settings.llm.mcp_reset_token")}"' in html

    res = client.post(url_for('settings.llm.mcp_settings_page'), data={'read_only': 'y'}, follow_redirects=True)
    assert b'MCP read-only mode switched on.' in res.data
    assert datastore.data['settings']['application']['mcp_read_only'] is True
    assert b'checked id="read_only" name="read_only" type="checkbox"' in res.data
    # Every connector is read-only now, so the per-connector ?readonly=1 address isn't offered
    assert b'mcp-url-readonly' not in res.data

    # Only the tools that change nothing are offered, and the assistant is told why
    tools = {t['name'] for t in _rpc(client, token, 'tools/list').json['result']['tools']}
    assert 'delete_watch' not in tools and 'create_watch' not in tools and 'list_watches' in tools
    res = _rpc(client, token, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                             'clientInfo': {'name': 'test', 'version': '1'}})
    assert 'read-only' in res.json['result']['instructions']

    # A client with the old tool list cached still can't change anything, it gets an error it can pass on
    res = _rpc(client, token, 'tools/call', {'name': 'delete_watch', 'arguments': {'watch': uuid}})
    result = res.json['result']
    assert result['isError'] is True
    assert 'read-only mode' in result['content'][0]['text'] and 'MCP Server' in result['content'][0]['text']
    assert uuid in datastore.data['watching']
    # Reading still works
    assert _rpc(client, token, 'tools/call', {'name': 'list_watches', 'arguments': {}}).json['result']['isError'] is False

    # Unticked, the box isn't sent at all
    res = client.post(url_for('settings.llm.mcp_settings_page'), data={}, follow_redirects=True)
    assert b'MCP read-only mode switched off.' in res.data
    assert {t['name'] for t in _rpc(client, token, 'tools/list').json['result']['tools']} == all_tools
    assert b'mcp-url-readonly' in res.data

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

    for page, active_switch in ((llm_page, llm_page), (mcp_page, mcp_page)):
        html = client.get(page).get_data(as_text=True)
        assert f'<li class="tab active">{ai_tab}</li>' in html, page
        assert html.count('<li class="tab active">') == 1, page
        for anchor in ('general', 'fetching', 'filters', 'ui-options', 'api', 'rss', 'timedate', 'proxies', 'info'):
            assert f'<li class="tab"><a href="{settings_page}#{anchor}">' in html, (page, anchor)
        assert f'href="{url_for("backups.create")}"' in html
        assert f'<a href="{active_switch}" class="settings-subtab active" aria-current="page">' in html, page


def test_ai_settings_csrf(client, live_server, measure_memory_usage, datastore_path):
    # The test config switches CSRF off, so prove the AI settings pages are protected with it switched back on
    import re
    app = client.application
    settings = app.config['DATASTORE'].data['settings']['application']
    token = settings['mcp_access_token']
    settings['mcp_read_only'] = False
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        # Every route that changes something refuses a POST without the CSRF token (a cross-site form post)
        for endpoint in ('settings.llm.llm_settings_page', 'settings.llm.mcp_settings_page',
                         'settings.llm.mcp_reset_token', 'settings.llm.llm_test', 'settings.llm.llm_clear',
                         'settings.llm.llm_clear_summary_cache'):
            res = client.post(url_for(endpoint), data={'read_only': 'y'})
            assert res.status_code == 400, f"{endpoint} accepted a POST without a CSRF token ({res.status_code})"
        assert settings['mcp_access_token'] == token and not settings.get('mcp_read_only')

        # The token in the page's form is accepted, for Save and for the "Regenerate MCP token" formaction button
        html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        res = client.post(url_for('settings.llm.mcp_settings_page'), data={'csrf_token': csrf_token, 'read_only': 'y'})
        assert res.status_code == 302 and settings['mcp_read_only'] is True
        res = client.post(url_for('settings.llm.mcp_reset_token'), data={'csrf_token': csrf_token, 'read_only': 'y'})
        assert res.status_code == 302 and settings['mcp_access_token'] != token
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
        settings['mcp_read_only'] = False
