#!/usr/bin/env python3
"""The MCP server at /mcp: stateless JSON-RPC, API-key auth, read-only tools."""
import json
import os

import pytest
from mcp_types.version import LATEST_HANDSHAKE_VERSION
from changedetectionio.blueprint.mcp.tools import UNTRUSTED_NOTE
from .util import delete_all_watches, new_mcp_token, wait_for_all_checks

T0 = 1700000000  # 2023-11-14T22:13:20Z


def _url(name):
    """A local test endpoint URL, distinct per name, so nothing ever fetches an outside host."""
    from flask import url_for
    return url_for('test_endpoint', _external=True, id=name)


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    """The MCP server is off until the switch on its settings tab is on, these tests are about it being on, with
    tokens with every tool allowed (a token's permissions grid has its own tests in test_mcp_notifications.py and
    test_mcp_settings_page.py)."""
    client.application.config['DATASTORE'].data['settings']['application']['mcp_enabled'] = True


def _rpc(client, method, params=None, msg_id=1, headers=None, api_key=None):
    body = {'jsonrpc': '2.0', 'method': method}
    if params is not None:
        body['params'] = params
    if msg_id is not None:
        body['id'] = msg_id
    h = {'x-api-key': api_key} if api_key else {}
    h.update(headers or {})
    return client.post('/mcp/v1', data=json.dumps(body), content_type='application/json', headers=h)


def _call(client, api_key, tool, **arguments):
    res = _rpc(client, 'tools/call', {'name': tool, 'arguments': arguments}, api_key=api_key)
    assert res.status_code == 200, res.data
    return res.json['result']


def _setup(datastore):
    group = datastore.add_tag('competitors')
    policy = datastore.add_watch(url=_url('privacy'),
                                 extras={'title': 'Privacy Policy', 'paused': True, 'tags': [group]})
    w = datastore.data['watching'][policy]
    w.save_history_blob('Intro\nWe may share data with\nour payment processor.\nOutro', T0, 'a')
    w.save_history_blob('Intro\nWe may share data with\nour payment processor and advertising partners.\nOutro', T0 + 100, 'b')
    broken = datastore.add_watch(url=_url('broken'), extras={'title': 'Broken page', 'paused': True})
    datastore.data['watching'][broken]['last_error'] = 'Connection refused'
    return group, policy, broken


def test_mcp_protocol(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)

    res = _rpc(client, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                       'clientInfo': {'name': 'test', 'version': '1'}}, api_key=api_key)
    assert res.status_code == 200
    result = res.json['result']
    assert result['protocolVersion'] == '2025-06-18'
    assert result['capabilities'] == {'tools': {'listChanged': False}}
    assert result['serverInfo']['name'] == 'changedetection.io'
    assert 'get_changes' in result['instructions']
    # A version we don't know gets our newest
    res = _rpc(client, 'initialize', {'protocolVersion': '1999-01-01', 'capabilities': {},
                                       'clientInfo': {'name': 'test', 'version': '1'}}, api_key=api_key)
    assert res.json['result']['protocolVersion'] == LATEST_HANDSHAKE_VERSION
    # The newer stateless-envelope revisions aren't spoken here, a client asking for one is offered a handshake version
    res = _rpc(client, 'initialize', {'protocolVersion': '2026-07-28', 'capabilities': {},
                                       'clientInfo': {'name': 'test', 'version': '1'}}, api_key=api_key)
    assert res.json['result']['protocolVersion'] == LATEST_HANDSHAKE_VERSION

    # Notifications get no answer
    res = _rpc(client, 'notifications/initialized', msg_id=None, api_key=api_key)
    assert res.status_code == 202 and res.data == b''

    assert _rpc(client, 'ping', api_key=api_key).json == {'jsonrpc': '2.0', 'id': 1, 'result': {}}

    res = _rpc(client, 'tools/list', api_key=api_key)
    tools = {t['name']: t for t in res.json['result']['tools']}
    read_only = {'list_watches', 'get_watch', 'list_tags', 'get_changes', 'get_diff', 'get_snapshot',
                 'get_system_info', 'list_notifications', 'notification_services',
                 'list_snapshots', 'find_change', 'get_history', 'line_timeline', 'get_screenshot',
                 # From the built-in restock_diff plugin (register_mcp_tools, see test_mcp_plugin_tools.py)
                 'restock_status'}
    # update_* can replace settings (e.g. the whole notification URL list), so they count as destructive too
    destructive = {'delete_watch', 'clear_history', 'delete_tag', 'remove_notification', 'update_watch', 'update_tag'}
    assert read_only | destructive <= set(tools)
    assert all(t['inputSchema']['type'] == 'object' for t in tools.values())
    assert {n for n, t in tools.items() if t['annotations']['readOnlyHint']} == read_only
    assert {n for n, t in tools.items() if t['annotations']['destructiveHint']} == destructive
    assert tools['get_changes']['inputSchema']['required'] == ['from']

    # ?readonly=1 offers only the read-only tools, and refuses the others even when called by name, as a tool error
    # the assistant can read and pass on
    res = client.post('/mcp/v1?readonly=1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                      content_type='application/json', headers={'x-api-key': api_key})
    assert {t['name'] for t in res.json['result']['tools']} == read_only
    # Tools that make the server fetch outside pages say so
    assert all(tools[n]['annotations']['openWorldHint'] for n in ('create_watch', 'import_watches', 'recheck_watches'))
    assert all(t['annotations'].get('title') for t in tools.values())
    res = client.post('/mcp/v1?readonly=1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                          'params': {'name': 'delete_watch', 'arguments': {'watch': 'x'}}}),
                      content_type='application/json', headers={'x-api-key': api_key})
    assert res.json['result']['isError'] is True
    assert '?readonly=1' in res.json['result']['content'][0]['text']

    # Requests are checked against the protocol schema (mcp-types)
    res = _rpc(client, 'tools/call', {'arguments': {}}, api_key=api_key)
    assert res.json['error']['code'] == -32602 and 'name' in res.json['error']['message']
    res = _rpc(client, 'initialize', {'protocolVersion': '2025-06-18'}, api_key=api_key)
    assert res.json['error']['code'] == -32602, "initialize without capabilities/clientInfo"
    # A protocol version header we don't speak is refused (MCP spec), one we do is fine
    assert _rpc(client, 'ping', api_key=api_key, headers={'MCP-Protocol-Version': '1999-01-01'}).status_code == 400
    assert _rpc(client, 'ping', api_key=api_key, headers={'MCP-Protocol-Version': '2025-06-18'}).status_code == 200

    # Batches
    res = client.post('/mcp/v1', data=json.dumps([{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
                                               {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                                               {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}]),
                      content_type='application/json', headers={'x-api-key': api_key})
    assert [m['id'] for m in res.json] == [1, 2]

    # Errors
    assert _rpc(client, 'resources/list', api_key=api_key).json['error']['code'] == -32601
    res = _rpc(client, 'tools/call', {'name': 'delete_everything', 'arguments': {}}, api_key=api_key)
    assert res.json['error']['code'] == -32602
    res = client.post('/mcp/v1', data='{not json', content_type='application/json', headers={'x-api-key': api_key})
    assert res.status_code == 400 and res.json['error']['code'] == -32700
    assert client.post('/mcp/v1', data=json.dumps({'id': 1}), content_type='application/json',
                       headers={'x-api-key': api_key}).json['error']['code'] == -32600
    # Stateless: no SSE stream, no session
    assert client.get('/mcp/v1').status_code == 405
    assert client.delete('/mcp/v1', headers={'x-api-key': api_key}).status_code == 405


def test_mcp_auth(client, live_server, measure_memory_usage, datastore_path):
    """MCP has its own named access tokens, separate from the REST API key, and one is always required."""
    datastore = client.application.config['DATASTORE']
    settings = datastore.data['settings']['application']
    settings.pop('mcp_tokens', None)
    # A fresh install has none, so nothing can connect until one is added
    assert _rpc(client, 'ping', api_key='').status_code == 401
    token = new_mcp_token(client, name='Claude Code, laptop')
    assert token.startswith('cdio_mcp_') and token != settings.get('api_access_token')
    # Only its hash is stored, never the token itself
    stored = list(settings['mcp_tokens'].values())[0]
    assert token not in str(settings['mcp_tokens']) and stored['hint'] == token[:13]
    assert stored['last_used'] is None

    res = _rpc(client, 'ping')
    # 401 with a Bearer challenge (MCP spec), so an OAuth client knows to sign in; a wrong Origin stays 403
    assert res.status_code == 401 and res.headers['WWW-Authenticate'].startswith('Bearer ')
    assert _rpc(client, 'ping', api_key='wrong').status_code == 401
    # The REST API key is not an MCP token
    assert _rpc(client, 'ping', api_key=settings.get('api_access_token')).status_code == 401
    assert _rpc(client, 'ping', headers={'Authorization': f'Bearer {settings.get("api_access_token")}'}).status_code == 401
    # Bearer (what the copyable configs use) or x-api-key
    assert _rpc(client, 'ping', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    assert _rpc(client, 'ping', api_key=token).status_code == 200
    # "Last used", and which client from initialize
    assert stored['last_used']
    _rpc(client, 'initialize', {'protocolVersion': '2025-06-18', 'capabilities': {},
                                'clientInfo': {'name': 'claude-code', 'version': '1'}}, api_key=token)
    assert stored['last_client'] == 'claude-code'
    # A web page in someone's browser must not reach it (DNS rebinding), the assistant itself sends no Origin
    assert _rpc(client, 'ping', api_key=token, headers={'Origin': 'https://evil.example'}).status_code == 403
    from urllib.parse import urlsplit
    from flask import url_for
    own = urlsplit(url_for('mcp.endpoint', _external=True))
    assert _rpc(client, 'ping', api_key=token, headers={'Origin': f'{own.scheme}://{own.netloc}'}).status_code == 200

    # Required even with "API access requires key" off, there is no open mode
    settings['api_access_token_enabled'] = False
    try:
        assert _rpc(client, 'ping').status_code == 401
        # and a password-protected UI never sends an assistant to the login page
        settings['password'] = 'something'
        assert _rpc(client, 'ping', api_key=token).status_code == 200
    finally:
        settings['password'] = False
        settings['api_access_token_enabled'] = True

    # Revoked: refused at once
    settings['mcp_tokens'].clear()
    assert _rpc(client, 'ping', api_key=token).status_code == 401


def test_mcp_tools(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    group, policy, broken = _setup(datastore)

    result = _call(client, api_key, 'list_watches')
    assert result['isError'] is False and result['structuredContent']['total'] == 2
    text = result['content'][0]['text']
    assert f"Privacy Policy | {_url('privacy')} | uuid {policy}" in text
    assert 'tags: competitors' in text and 'error: Connection refused' in text
    assert [w['uuid'] for w in _call(client, api_key, 'list_watches', with_errors=True)['structuredContent']['watches']] == [broken]
    assert _call(client, api_key, 'list_watches', tag='competitors')['structuredContent']['total'] == 1
    assert _call(client, api_key, 'list_watches', search='broken')['structuredContent']['total'] == 1
    assert _call(client, api_key, 'list_watches', tag='nope')['isError'] is True

    # History stats for every monitor in one call, and sorting by them: "which monitors have years of history?"
    old = datastore.add_watch(url=_url('old'), extras={'title': 'Old page', 'paused': True})
    for i, day in enumerate((-800, -400, -10)):
        datastore.data['watching'][old].save_history_blob(f'version {i}', T0 + day * 86400, f'o{i}')
    rows = {w['uuid']: w for w in _call(client, api_key, 'list_watches')['structuredContent']['watches']}
    assert (rows[policy]['snapshots'], rows[policy]['history_days']) == (2, 0.0)
    assert rows[old]['snapshots'] == 3 and rows[old]['history_days'] == 790.0
    assert rows[old]['first_snapshot'] == _iso(T0 - 800 * 86400)
    assert rows[broken]['snapshots'] == 0 and rows[broken]['first_snapshot'] is None
    for sort, order in (('first_snapshot', [old, policy, broken]), ('snapshots', [old, policy, broken]),
                        ('history_span', [old, policy, broken])):
        result = _call(client, api_key, 'list_watches', sort=sort)
        assert [w['uuid'] for w in result['structuredContent']['watches']] == order, sort
    assert '3 snapshots since' in result['content'][0]['text'] and 'longest history first' in result['content'][0]['text']
    assert _call(client, api_key, 'list_watches', sort='bogus')['isError'] is True
    datastore.delete(old)

    result = _call(client, api_key, 'list_tags')
    assert result['structuredContent']['tags'] == [{'uuid': group, 'title': 'competitors', 'monitors': 1,
                                                    'notification_muted': False}]

    info = _call(client, api_key, 'get_watch', watch=policy)['structuredContent']
    assert info['snapshots'] == 2 and info['tags'] == ['competitors']
    assert 'notification_urls' not in info, "never the URLs, they hold tokens"
    missing = _call(client, api_key, 'get_watch', watch='no-such-uuid')
    assert missing['isError'] is True and 'list_watches' in missing['content'][0]['text']
    # By part of the title or URL, with the latest change included
    result = _call(client, api_key, 'get_watch', watch='privacy')
    assert result['structuredContent']['uuid'] == policy
    assert '+our payment processor and advertising partners.' in result['structuredContent']['latest_change']['diff']
    assert UNTRUSTED_NOTE in result['content'][0]['text']
    # Ambiguous: the candidates come back to choose from
    ambiguous = _call(client, api_key, 'get_watch', watch='test-endpoint')
    assert ambiguous['isError'] is True and policy in ambiguous['content'][0]['text'] and broken in ambiguous['content'][0]['text']

    result = _call(client, api_key, 'get_changes', **{'from': T0, 'to': T0 + 200, 'tag': 'competitors'})
    text = result['content'][0]['text']
    assert text.startswith(UNTRUSTED_NOTE)
    assert '-our payment processor.\n+our payment processor and advertising partners.' in text
    assert result['structuredContent']['total'] == 1
    assert _call(client, api_key, 'get_changes', to='2023-11-15')['isError'] is True  # 'from' is required

    result = _call(client, api_key, 'get_diff', watch=policy)
    assert result['content'][0]['text'].startswith(UNTRUSTED_NOTE)
    assert '+our payment processor and advertising partners.' in result['structuredContent']['diff']
    assert result['structuredContent']['from_timestamp'] == T0
    assert _call(client, api_key, 'get_diff', watch=broken)['isError'] is True  # no snapshots

    result = _call(client, api_key, 'get_snapshot', watch=policy, timestamp='previous', max_chars=100)
    assert not result['isError'], result['content'][0]['text']
    assert result['structuredContent']['timestamp'] == T0
    assert 'our payment processor.' in result['content'][0]['text']
    result = _call(client, api_key, 'get_snapshot', watch=policy, max_chars=100)
    assert result['structuredContent']['truncated'] is False
    assert 'advertising partners' in result['structuredContent']['content']
    # An ISO date picks the snapshot at or before it
    assert _call(client, api_key, 'get_snapshot', watch=policy, timestamp='2023-11-14T22:14:00Z')['structuredContent']['timestamp'] == T0

    client.post('/tags/delete_all', follow_redirects=True)
    delete_all_watches(client)


def test_mcp_write_tools(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    watching = datastore.data['watching']

    # Create, with validation shared with the REST API
    result = _call(client, api_key, 'create_watch', url=_url('new-page'), title='New page',
                   tags=['Shops'], check_interval={'hours': 6})
    assert result['isError'] is False
    new = result['structuredContent']['uuid']
    assert watching[new]['time_between_check']['hours'] == 6 and result['structuredContent']['tags'] == ['Shops']
    bad = _call(client, api_key, 'create_watch', url='javascript:alert(1)')
    assert bad['isError'] is True and 'Invalid or unsupported URL' in bad['content'][0]['text']

    # Import, capped per call
    result = _call(client, api_key, 'import_watches', urls=[_url('a'), _url('b'), 'ftp:/nope'],
                   tags=['Bulk'])
    assert len(result['structuredContent']['created']) == 2 and len(result['structuredContent']['failed']) == 1
    too_many = _call(client, api_key, 'import_watches', urls=[_url(i) for i in range(101)])
    assert too_many['isError'] is True and 'At most 100' in too_many['content'][0]['text']

    # Update by name: pause, mute, interval; unknown/invalid values come back as errors
    result = _call(client, api_key, 'update_watch', watch='new-page', paused=True, notification_muted=True,
                   include_filters=['#price'])
    assert result['isError'] is False
    assert watching[new]['paused'] and watching[new]['notification_muted'] and watching[new]['include_filters'] == ['#price']
    assert _call(client, api_key, 'update_watch', watch=new, url='javascript:alert(1)')['isError'] is True
    assert _call(client, api_key, 'update_watch', watch=new)['isError'] is True  # nothing to change

    # Tags by name, created when missing
    result = _call(client, api_key, 'add_tags', watches=[new, 'id=a'], tags=['Competitors', 'Shops'])
    assert result['isError'] is False
    assert set(_call(client, api_key, 'get_watch', watch=new)['structuredContent']['tags']) == {'Shops', 'Competitors'}
    _call(client, api_key, 'remove_tags', watches=[new], tags=['Shops'])
    assert _call(client, api_key, 'get_watch', watch=new)['structuredContent']['tags'] == ['Competitors']
    assert _call(client, api_key, 'remove_tags', watches=[new], tags=['No such tag'])['isError'] is True
    tag = _call(client, api_key, 'create_tag', title='Muted group', notification_muted=True)['structuredContent']['uuid']
    _call(client, api_key, 'update_tag', tag='Muted group', title='Quiet group')
    assert datastore.data['settings']['application']['tags'][tag]['title'] == 'Quiet group'

    # Recheck only queues; paused monitors are skipped unless named
    assert _call(client, api_key, 'recheck_watches')['isError'] is True  # say what
    result = _call(client, api_key, 'recheck_watches', watches=[new])
    assert result['structuredContent']['queued'] + result['structuredContent']['skipped'] == 1
    assert _call(client, api_key, 'recheck_watches', tag='Competitors')['isError'] is False

    # Notifications: validated, secrets never come back
    bad = _call(client, api_key, 'add_notification', url='notaservice://nope')
    assert bad['isError'] is True
    result = _call(client, api_key, 'add_notification', url='discord://1234567/abcdefghijklmnop', watch=new)
    assert result['isError'] is False and 'abcdefghijklmnop' not in result['content'][0]['text']
    assert watching[new]['notification_urls'] == ['discord://1234567/abcdefghijklmnop']
    listed = _call(client, api_key, 'list_notifications', watch=new)
    assert listed['structuredContent']['notification_urls'][0]['position'] == 1
    assert 'abcdefghijklmnop' not in json.dumps(listed)
    _call(client, api_key, 'remove_notification', watch=new, position=1)
    assert watching[new]['notification_urls'] == []
    assert _call(client, api_key, 'remove_notification', watch=new, position=1)['isError'] is True

    info = _call(client, api_key, 'get_system_info')['structuredContent']
    assert info['watch_count'] == len(watching)
    assert info['fetch_workers'] >= 1 and info['checking_now'] == len(info['checking']) <= 10
    assert isinstance(info['queue_size'], int) and isinstance(info['overdue_watches'], int)

    # Destructive: never 'all', one resolved monitor at a time
    count = len(watching)
    for ref in ('all', 'ALL', ' all '):
        refused = _call(client, api_key, 'delete_watch', watch=ref)
        assert refused['isError'] is True and "isn't possible" in refused['content'][0]['text']
    assert len(watching) == count, "nothing was deleted"
    assert _call(client, api_key, 'delete_watch', watch='test-endpoint')['isError'] is True  # ambiguous
    assert len(watching) == count

    watching[new].save_history_blob('one', T0, 'one')
    _call(client, api_key, 'clear_history', watch=new)
    assert watching[new].history_n == 0 and new in watching
    _call(client, api_key, 'delete_tag', tag='Quiet group')
    assert tag not in datastore.data['settings']['application']['tags']
    _call(client, api_key, 'delete_watch', watch=new)
    assert new not in watching and len(watching) == count - 1

    client.post('/tags/delete_all', follow_redirects=True)
    delete_all_watches(client)


def test_mcp_argument_validation(client, live_server, measure_memory_usage, datastore_path):
    """Bad arguments come back as a tool error listing every problem (the model can fix them), never silently ignored."""
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('validate'), extras={'paused': False})

    # A typo'd argument is an error, and nothing is changed
    result = _call(client, api_key, 'update_watch', watch=uuid, pausd=True, title='Changed')
    assert result['isError'] is True and 'unknown argument(s) pausd' in result['content'][0]['text']
    assert datastore.data['watching'][uuid].get('title') != 'Changed'
    # A string where a boolean belongs would have stored "false", which is truthy
    result = _call(client, api_key, 'update_watch', watch=uuid, paused='false')
    assert result['isError'] is True and 'paused: must be of type boolean' in result['content'][0]['text']
    assert not datastore.data['watching'][uuid].get('paused')
    # Values are checked against the same API spec as REST: lengths, enums, patterns
    result = _call(client, api_key, 'update_watch', watch=uuid, title='x' * 6000, processor='nope')
    text = result['content'][0]['text']
    assert result['isError'] is True and 'title: longer than 5000 characters' in text and 'processor: must be one of' in text
    assert 'xxxxxxxxxx' not in text, "the value isn't repeated back"
    assert _call(client, api_key, 'update_watch', watch=uuid, fetch_backend='evil')['isError'] is True
    # The limits are in the tool's schema, so the model sees them up front
    res = _rpc(client, 'tools/list', api_key=api_key)
    update = next(t for t in res.json['result']['tools'] if t['name'] == 'update_watch')['inputSchema']['properties']
    assert update['title']['maxLength'] == 5000 and 'text_json_diff' in update['processor']['enum']
    assert update['include_filters']['maxItems'] == 100

    # Out of range, and several problems at once
    result = _call(client, api_key, 'list_watches', limit=0, offset=-1)
    text = result['content'][0]['text']
    assert result['isError'] is True and 'limit' in text and 'offset' in text
    # Unix seconds are fine where a date is expected
    assert _call(client, api_key, 'get_changes', **{'from': T0})['isError'] is False

    # Results say when nothing actually changed
    datastore.add_tag('Seen')
    _call(client, api_key, 'add_tags', watches=[uuid], tags=['Seen'])
    again = _call(client, api_key, 'add_tags', watches=[uuid], tags=['Seen'])
    assert again['structuredContent']['changed'] == 0 and 'already had them' in again['content'][0]['text']

    client.post('/tags/delete_all', follow_redirects=True)
    delete_all_watches(client)


def test_mcp_sizes_fit_client_limits():
    """Claude Code cuts server instructions and each tool description at 2048 bytes (apify-mcp-server#1589)."""
    from changedetectionio.blueprint.mcp import INSTRUCTIONS
    from changedetectionio.blueprint.mcp.tools import definitions
    assert len(INSTRUCTIONS.encode()) < 2048
    for tool in definitions():
        assert len(tool['description'].encode()) < 2048, tool['name']


def test_changes_time_budget():
    """A report that runs out of time returns what it has instead of holding the request open."""
    from changedetectionio.changes_report import group_changes, render_unified
    report = group_changes([object()], T0, T0 + 100, time_budget=1e-9)
    assert report['incomplete'] is True and report['watches'] == []
    assert 'Incomplete' in render_unified(report)


def test_mcp_snapshot_unfiltered(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """get_snapshot unfiltered=true: the whole page from the HTML saved with the snapshot, for questions the filters
    don't cover ("the fried cheese prices on all my restaurant menus" when the filter picks out the beer)."""
    from changedetectionio.blueprint.mcp import tools
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    menus = datastore.add_tag('restaurant menus')
    page = ('<html><body><h1>Menu</h1><div id="beer">Pale ale $8</div>'
            '<div id="food">Fried cheese $12</div></body></html>')
    uuids = []
    for n, name in enumerate(('Bistro', 'Cafe', 'Diner')):
        uuid = datastore.add_watch(url=_url(f'{name.lower()}-menu'),
                                   extras={'title': name, 'paused': True, 'tags': [menus], 'include_filters': ['#beer']})
        w = datastore.data['watching'][uuid]
        w.save_history_blob('Pale ale $8', T0 + n, 'a')
        w.save_last_fetched_html(timestamp=T0 + n, contents=page)
        uuids.append(uuid)
    # A JSON one: no HTML to convert, given as it was fetched
    api = datastore.add_watch(url=_url('api-menu-json'), extras={'title': 'Api', 'paused': True})
    datastore.data['watching'][api]['content-type'] = 'application/json'
    datastore.data['watching'][api].save_history_blob('{"beer": 8}', T0, 'j')
    datastore.data['watching'][api].save_last_fetched_html(timestamp=T0, contents='{"beer": 8, "fried_cheese": 12}')

    # Filtered by default, the whole page with unfiltered
    result = _call(client, api_key, 'get_snapshot', watch=uuids[0])
    assert 'Fried cheese' not in result['structuredContent']['content'] and result['structuredContent']['source'] == 'filtered'
    result = _call(client, api_key, 'get_snapshot', watch=uuids[0], unfiltered=True)
    assert not result['isError'], result
    assert 'Fried cheese $12' in result['structuredContent']['content'] and '<div' not in result['structuredContent']['content']
    assert result['structuredContent']['source'] == 'html' and 'before filters' in result['content'][0]['text']
    result = _call(client, api_key, 'get_snapshot', watch=api, unfiltered=True)
    assert result['structuredContent']['content'] == '{"beer": 8, "fried_cheese": 12}' and result['structuredContent']['source'] == 'raw'

    # The whole tag in one call, paged
    result = _call(client, api_key, 'get_snapshot', tag='restaurant menus', unfiltered=True, limit=2)
    data = result['structuredContent']
    assert [s['title'] for s in data['snapshots']] == ['Bistro', 'Cafe'] and data['total'] == 3 and data['next_offset'] == 2
    assert all('Fried cheese $12' in s['content'] for s in data['snapshots'])
    assert 'call again with offset=2' in result['content'][0]['text']
    data = _call(client, api_key, 'get_snapshot', tag='restaurant menus', unfiltered=True, offset=2)['structuredContent']
    assert [s['title'] for s in data['snapshots']] == ['Diner'] and data['next_offset'] is None and 'warning' not in data
    data = _call(client, api_key, 'get_snapshot', watches=['Bistro', 'Api'], unfiltered=True)['structuredContent']
    assert {s['source'] for s in data['snapshots']} == {'html', 'raw'}

    # No saved page (only the newest two snapshots keep theirs): the filtered text, saying so
    for name in os.listdir(datastore.data['watching'][uuids[1]].data_dir):
        if name.endswith('.html.br'):
            os.unlink(os.path.join(datastore.data['watching'][uuids[1]].data_dir, name))
    result = _call(client, api_key, 'get_snapshot', watch=uuids[1], unfiltered=True)
    assert result['structuredContent']['source'] == 'snapshot' and 'only kept for the newest two' in result['content'][0]['text']

    # Many matches: a warning the assistant can act on
    monkeypatch.setattr(tools, 'SNAPSHOT_BATCH_WARN', 2)
    result = _call(client, api_key, 'get_snapshot', tag='restaurant menus', limit=1)
    assert result['content'][0]['text'].startswith('Warning: 3 monitors match, this could take a while.')
    assert 'Warning' in result['structuredContent']['warning']

    # One or several, not both
    assert _call(client, api_key, 'get_snapshot', watch=uuids[0], tag='restaurant menus')['isError'] is True
    assert _call(client, api_key, 'get_snapshot')['isError'] is True

    client.post('/tags/delete_all', follow_redirects=True)
    delete_all_watches(client)


def _menu_history(datastore):
    """A restaurant menu whose prices go up, then a broken capture: the history the three history tools are for."""
    uuid = datastore.add_watch(url=_url('bistro-menu'), extras={'title': 'Bistro menu', 'paused': True})
    w = datastore.data['watching'][uuid]
    menu = 'Soups\nBeef broth 79\nMains\nSchnitzel 239\nGoulash 249\n' + 'Opening hours Mon-Sun 11-22\n' * 40
    w.save_history_blob(menu, T0, 'a')
    w.save_history_blob(menu.replace('Schnitzel 239', 'Schnitzel 259'), T0 + 100, 'b')
    w.save_history_blob(menu.replace('Schnitzel 239', 'Schnitzel 259').replace('Beef broth 79', 'Beef broth 85'), T0 + 200, 'c')
    w.save_history_blob(menu.replace('Schnitzel 239', 'Schnitzel 279').replace('Beef broth 79', 'Beef broth 85'), T0 + 300, 'd')
    # Back to 259 for a while (a text can come and go), then the page breaks
    w.save_history_blob(menu.replace('Schnitzel 239', 'Schnitzel 259').replace('Beef broth 79', 'Beef broth 89'), T0 + 400, 'e')
    w.save_history_blob('Error: Cannot set property', T0 + 500, 'f')
    return uuid


def _iso(ts):
    from changedetectionio.changes_report import _iso as iso
    return iso(ts)


def test_mcp_history_tools(client, live_server, measure_memory_usage, datastore_path):
    """list_snapshots, find_change and get_history: 'how did the prices on this menu change over time?' in a few
    calls instead of one get_snapshot per date."""
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = _menu_history(datastore)
    D = [_iso(T0 + i * 100) for i in range(6)]

    # get_watch says where the history starts
    assert _call(client, api_key, 'get_watch', watch=uuid)['structuredContent']['first_snapshot'] == '2023-11-14T22:13:20Z'

    # list_snapshots: every date (ISO only), the broken capture flagged
    result = _call(client, api_key, 'list_snapshots', watch='Bistro')
    data = result['structuredContent']
    assert data['total'] == 6 and [s['date'] for s in data['snapshots']] == D
    assert [s.get('flag') for s in data['snapshots']] == [None] * 5 + ['shrunk']
    assert 'SHRUNK' in result['content'][0]['text'] and '/' not in str(data['snapshots'][0]), "never a path on disk"
    assert 'timestamp' not in data['snapshots'][0], "one date format"
    data = _call(client, api_key, 'list_snapshots', watch=uuid, **{'from': T0 + 100, 'to': T0 + 300}, limit=2)['structuredContent']
    assert data['in_range'] == 3 and [s['date'] for s in data['snapshots']] == D[1:3]

    # find_change: each period the text was there, with when it went away, and every matching line
    result = _call(client, api_key, 'find_change', watch=uuid, text='schnitzel 259')
    found = result['structuredContent']
    assert not result['isError'] and found['matching_snapshots'] == 3 and found['snapshots_searched'] == 6
    assert [(p['first_seen'], p['last_seen'], p['gone_at']) for p in found['periods']] == [(D[1], D[2], D[3]), (D[4], D[4], D[5])]
    assert found['periods'][0]['line'] == 'Schnitzel 259' and result['content'][0]['text'].startswith(UNTRUSTED_NOTE)
    # Case sensitive, a range, a regex, still there at the end
    assert _call(client, api_key, 'find_change', watch=uuid, text='schnitzel 259', case_sensitive=True)['structuredContent']['periods'] == []
    found = _call(client, api_key, 'find_change', watch=uuid, text='Schnitzel 259', **{'to': T0 + 250})['structuredContent']
    assert found['snapshots_searched'] == 3 and found['periods'][0]['gone_at'] is None
    found = _call(client, api_key, 'find_change', watch=uuid, text=r'Beef broth 8\d', regex=True)['structuredContent']
    assert [(p['first_seen'], p['gone_at']) for p in found['periods']] == [(D[2], D[5])]
    # Every distinct matching line, not only the first of each period: broth 85 then 89 are one period
    assert [(m['line'], m['first_seen'], m['last_seen']) for m in found['lines']] == \
           [('Beef broth 85', D[2], D[3]), ('Beef broth 89', D[4], D[4])]
    assert 'Not found' in _call(client, api_key, 'find_change', watch=uuid, text='Lobster')['content'][0]['text']
    # A bad regex and an empty text are errors the assistant can fix
    result = _call(client, api_key, 'find_change', watch=uuid, text='(unclosed', regex=True)
    assert result['isError'] and 'Invalid regex' in result['content'][0]['text']
    assert _call(client, api_key, 'find_change', watch=uuid, text='  ')['isError'] is True

    # get_history: the first in full, the rest as diffs
    result = _call(client, api_key, 'get_history', watch=uuid, sample=3)
    data, text = result['structuredContent'], result['content'][0]['text']
    assert [data['base']['date']] + [p['date'] for p in data['patches']] == [D[0], D[3], D[5]], \
        "evenly spaced, first and last included"
    # The broken capture at the end is a real change: every line went
    assert data['patches'][-1]['diff'].count('-Opening hours') == 40 and '+Error: Cannot set property' in data['patches'][-1]['diff']
    text = _call(client, api_key, 'get_history', watch=uuid, **{'to': T0 + 400})['content'][0]['text']
    assert text.count('Opening hours') == 40, "the unchanged text is sent once, not once per snapshot"
    assert '-Schnitzel 239\n+Schnitzel 279' in data['patches'][0]['diff']
    assert '=== 2023-11-14T22:15:00Z: changes from 2023-11-14T22:13:20Z ===\n@@ -4 +4 @@\n-Schnitzel 239\n+Schnitzel 259' in text
    # Against the first: each patch on its own
    data = _call(client, api_key, 'get_history', watch=uuid, timestamps=[T0, T0 + 200, T0 + 400], relative_to='first')['structuredContent']
    assert all(p['against'] == D[0] for p in data['patches'])
    assert '+Beef broth 89' in data['patches'][1]['diff'] and '-Beef broth 79' in data['patches'][1]['diff']
    # Same text twice says so, ISO dates resolve to the snapshot at or before them
    data = _call(client, api_key, 'get_history', watch=uuid, timestamps=[T0 + 100, T0 + 150, T0 + 200])['structuredContent']
    assert len(data['patches']) == 1 and data['base']['date'] == D[1]
    # Limits
    result = _call(client, api_key, 'get_history', watch=uuid, max_lines=1)
    assert result['structuredContent']['truncated'] and 'more lines' in result['content'][0]['text']
    assert 'line_timeline' in result['content'][0]['text'], "points at the smaller tool when diffs get cut"
    assert _call(client, api_key, 'get_history', watch=uuid, timestamps=[T0], sample=3)['isError'] is True
    assert _call(client, api_key, 'get_history', watch=uuid, **{'from': T0 + 10_000})['isError'] is True

    delete_all_watches(client)


def test_mcp_line_timeline(client, live_server, measure_memory_usage, datastore_path):
    """line_timeline: what was added to a list and when, each line once, even when the page flips between layouts."""
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('band-tour'), extras={'title': 'Band tour', 'paused': True})
    w = datastore.data['watching'][uuid]
    header = 'Tour Dates\nTickets\n'
    w.save_history_blob(header + 'Oct 9 Manchester\nOct 29 Prague', T0, 'a')
    w.save_history_blob(header + 'Oct 9 Manchester\nOct 29 Prague\nFeb 6 Leeuwarden', T0 + 100, 'b')
    # The page breaks (a different layout), then comes back: nothing in it is new again
    w.save_history_blob('Loading...', T0 + 200, 'c')
    w.save_history_blob(header + 'Oct 29 Prague\nFeb 6 Leeuwarden\nJul 4 Helsinki', T0 + 300, 'd')

    result = _call(client, api_key, 'line_timeline', watch=uuid)
    data, text = result['structuredContent'], result['content'][0]['text']
    assert [(e['line'], e['first_seen'], e['still_there']) for e in data['lines']] == \
           [('Feb 6 Leeuwarden', _iso(T0 + 100), True), ('Loading...', _iso(T0 + 200), False),
            ('Jul 4 Helsinki', _iso(T0 + 300), True)], "only lines added after the first snapshot, each once"
    assert data['left_out_at_start'] == 4 and 'include_start=true' in text and text.startswith(UNTRUSTED_NOTE)
    # Everything, and what went away
    data = _call(client, api_key, 'line_timeline', watch=uuid, include_start=True, still_there=False)['structuredContent']
    assert [(e['line'], e['last_seen']) for e in data['lines']] == [('Oct 9 Manchester', _iso(T0 + 100)),
                                                                    ('Loading...', _iso(T0 + 200))]
    assert data['lines'][0]['at_start'] is True
    # A filter, a regex, a range
    data = _call(client, api_key, 'line_timeline', watch=uuid, text='prague', include_start=True)['structuredContent']
    assert [(e['line'], e['first_seen'], e['last_seen']) for e in data['lines']] == [('Oct 29 Prague', _iso(T0), _iso(T0 + 300))]
    data = _call(client, api_key, 'line_timeline', watch=uuid, text=r'^(Feb|Jul) ', regex=True)['structuredContent']
    assert [e['line'] for e in data['lines']] == ['Feb 6 Leeuwarden', 'Jul 4 Helsinki']
    data = _call(client, api_key, 'line_timeline', watch=uuid, **{'from': T0 + 100})['structuredContent']
    assert [e['line'] for e in data['lines']] == ['Loading...', 'Jul 4 Helsinki'], "the range's first snapshot is the start"
    assert _call(client, api_key, 'line_timeline', watch=uuid, text='(x', regex=True)['isError'] is True

    delete_all_watches(client)


def test_mcp_history_summaries(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The answers that used to overflow: list_snapshots summarises long histories, get_history samples instead of
    refusing, find_change counts per period, and SHRUNK compares with the median so a short page isn't flagged."""
    from changedetectionio.blueprint.mcp import tools
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('news'), extras={'title': 'News', 'paused': True})
    w = datastore.data['watching'][uuid]
    import random
    rng = random.Random(1)
    day = 86400
    for i in range(70):
        headline = f"Headline {i} about {'Ukraine' if i % 10 == 0 else 'art'}"
        body = '\n'.join(f"{rng.random()} filler {rng.random()}" for _ in range(60))
        # One error page, then back to normal
        w.save_history_blob('Error 503' if i == 40 else f"{headline}\n{body}", T0 + i * 7 * day, str(i))

    # Summary by default when long
    result = _call(client, api_key, 'list_snapshots', watch=uuid)
    data = result['structuredContent']
    assert data['summary'] is True and data['total'] == 70 and 'snapshots' not in data
    assert sum(data['by_month'].values()) == 70 and data['stored_bytes']['min'] < data['stored_bytes']['median']
    assert [(f['date'], f['flag']) for f in data['flagged']] == [(_iso(T0 + 40 * 7 * day), 'shrunk'),
                                                                 (_iso(T0 + 41 * 7 * day), 'recovered')]
    assert 'full=true' in result['content'][0]['text']
    assert len(_call(client, api_key, 'list_snapshots', watch=uuid, full=True, limit=500)['structuredContent']['snapshots']) == 70

    # get_history: more than the limit is sampled down, with a note, instead of an error
    monkeypatch.setattr(tools, 'HISTORY_MAX_SNAPSHOTS', 10)
    result = _call(client, api_key, 'get_history', watch=uuid, max_chars=200, max_lines=50)
    assert not result['isError'] and len(result['structuredContent']['patches']) == 9
    assert 'evenly spaced' in result['structuredContent']['notes'][0]

    # find_change: every matching headline, and how many new ones per period
    found = _call(client, api_key, 'find_change', watch=uuid, text='ukraine', group_by='year')['structuredContent']
    assert found['lines_total'] == 6 and sum(found['new_lines_by_year'].values()) == 6  # no. 40 is the error page
    assert _call(client, api_key, 'find_change', watch=uuid, text='x', group_by='week')['isError'] is True
    found = _call(client, api_key, 'find_change', watch=uuid, text='Headline', max_lines=5)['structuredContent']
    assert found['lines_total'] == 69 and len(found['lines']) == 5

    delete_all_watches(client)


def test_mcp_get_watch_notes(client, live_server, measure_memory_usage, datastore_path):
    """get_watch says in words when a setting hides changes: trigger text, or nothing recorded for months although
    every check succeeds (the Metallica monitor with a 'Prague' trigger stayed silent for 17 months)."""
    import time
    from flask import url_for
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    # Added paused, with a local URL: unpaused with last_checked=0 the ticker queues it straight away, and the real
    # fetch sets last_error / a new snapshot, which (correctly) removes the "quiet" note - a race the test sometimes lost
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True),
                               extras={'title': 'Band', 'trigger_text': ['Prague'], 'paused': True})
    w = datastore.data['watching'][uuid]
    w.save_history_blob('Upcoming dates', int(time.time()) - 400 * 86400, 'a')
    # Checked an hour ago, so not due again (well inside the default recheck time) once unpaused
    w['last_checked'] = int(time.time()) - 3600
    w['paused'] = False
    wait_for_all_checks(client)
    info = _call(client, api_key, 'get_watch', watch=uuid)
    notes = info['structuredContent']['notes']
    assert any("trigger_text is set ('Prague')" in n for n in notes)
    assert any('Nothing recorded for 399 days' in n and 'trigger_text' in n for n in notes)
    assert info['content'][0]['text'].split('\n')[2].startswith('NOTE: '), "near the top, not buried"
    # A failing monitor isn't "quiet", it's broken, its error says so
    w['last_error'] = 'Error - 503'
    w['trigger_text'] = []
    assert 'notes' not in _call(client, api_key, 'get_watch', watch=uuid)['structuredContent']

    delete_all_watches(client)


def test_find_change_regex_timeout(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """A regex that backtracks for ever is stopped (the regex package's timeout, as the regex_replace Jinja2 filter
    uses), and the assistant is told so instead of getting 'not found'."""
    from changedetectionio.jinja2_custom.plugins import regex as regex_plugin
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('redos'), extras={'title': 'ReDoS', 'paused': True})
    datastore.data['watching'][uuid].save_history_blob('a' * 40 + '!', T0, 'a')
    monkeypatch.setattr(regex_plugin, 'REGEX_TIMEOUT_SECONDS', 0.2)
    # (the regex package optimises the textbook (a+)+$ away, (a|aa)+$ still backtracks)

    result = _call(client, api_key, 'find_change', watch=uuid, text='(a|aa)+$', regex=True)
    assert result['isError'] and 'took longer than' in result['content'][0]['text']
    # The model method raises it, for other callers (the UI) to handle as well
    with pytest.raises(TimeoutError):
        datastore.data['watching'][uuid].find_change('(a|aa)+$', regex=True)

    delete_all_watches(client)


def test_mcp_fetcher_and_proxy(client, live_server, measure_memory_usage, datastore_path):
    """create_watch / update_watch choose the fetcher and proxy (by name, as the user sees it), and say what a check
    will actually use. Proxy URLs hold passwords: they're never shown."""
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    requests_settings = datastore.data['settings']['requests']
    requests_settings['extra_proxies'] = [{'proxy_name': 'Czech exit', 'proxy_url': 'http://agent:s3cret@cz.example.com:3128'}]
    requests_settings['extra_browsers'] = [{'browser_name': 'stealth', 'browser_connection_url': 'ws://browser.example.com:3000'}]
    try:
        info = _call(client, api_key, 'get_system_info')
        data = info['structuredContent']
        assert {'id': 'ui-0Czech exit', 'label': 'Czech exit'} in data['proxies']
        assert 'html_requests' in data['fetchers'] and 'extra_browser_stealth' in data['fetchers']
        assert 's3cret' not in json.dumps(info) and 'browser.example.com' not in json.dumps(info)

        result = _call(client, api_key, 'create_watch', url=_url('shop'), proxy='czech exit',
                       fetch_backend='html_requests', paused=True)
        assert not result['isError'], result
        data = result['structuredContent']
        assert (data['proxy'], data['effective_proxy'], data['effective_fetcher']) == ('ui-0Czech exit', 'Czech exit', 'html_requests')
        assert 'through the proxy Czech exit' in result['content'][0]['text'] and 's3cret' not in json.dumps(result)
        uuid = data['uuid']
        assert datastore.data['watching'][uuid]['proxy'] == 'ui-0Czech exit'

        # get_watch says what a check uses; 'system' goes back to the defaults
        assert _call(client, api_key, 'get_watch', watch=uuid)['structuredContent']['effective_fetcher'] == 'html_requests'
        result = _call(client, api_key, 'update_watch', watch=uuid, proxy='system', fetch_backend='system')
        assert not result['isError'], result
        assert not datastore.data['watching'][uuid].get('proxy')
        assert result['structuredContent']['fetch_backend'] == 'system'

        # Mistakes name what's available, never a URL
        result = _call(client, api_key, 'create_watch', url=_url('shop-2'), proxy='Mars exit')
        assert result['isError'] and 'Czech exit (ui-0Czech exit)' in result['content'][0]['text']
        assert 's3cret' not in result['content'][0]['text']
        result = _call(client, api_key, 'update_watch', watch=uuid, fetch_backend='extra_browser_nope')
        assert result['isError'] and 'stealth' in result['content'][0]['text']
        assert not _call(client, api_key, 'update_watch', watch=uuid, fetch_backend='extra_browser_stealth')['isError']
    finally:
        requests_settings['extra_proxies'] = []
        requests_settings['extra_browsers'] = []
        delete_all_watches(client)


def test_mcp_screenshot_and_hashes(client, live_server, measure_memory_usage, datastore_path):
    """get_screenshot returns a readable slice of the (possibly very tall) latest screenshot as image content, and
    get_snapshot / get_history give each snapshot's SHA-256."""
    import base64
    import hashlib
    from io import BytesIO
    from PIL import Image
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    uuid = _menu_history(datastore)
    w = datastore.data['watching'][uuid]

    # No screenshot yet: says why
    result = _call(client, api_key, 'get_screenshot', watch=uuid)
    assert result['isError'] and 'browser fetchers' in result['content'][0]['text']

    # A tall full-page capture, 2048 x 6000: scaled to 1024 wide (3000 tall), sent 1568 at a time
    tall = BytesIO()
    Image.new('RGB', (2048, 6000), (200, 30, 30)).save(tall, 'PNG')
    w.save_screenshot(tall.getvalue())
    result = _call(client, api_key, 'get_screenshot', watch=uuid)
    assert not result['isError'], result
    data = result['structuredContent']
    assert (data['width'], data['height'], data['offset'], data['part_height'], data['next_offset']) == (1024, 3000, 0, 1568, 1568)
    image = result['content'][1]
    assert image['type'] == 'image' and image['mimeType'] == 'image/jpeg'
    with Image.open(BytesIO(base64.b64decode(image['data']))) as img:
        assert img.size == (1024, 1568)
    assert 'call again with offset=1568' in result['content'][0]['text']
    data = _call(client, api_key, 'get_screenshot', watch=uuid, offset=1568)['structuredContent']
    assert (data['offset'], data['part_height'], data['next_offset']) == (1568, 1432, None)
    result = _call(client, api_key, 'get_screenshot', watch=uuid, which='error')
    assert result['isError'] and 'failed check' in result['content'][0]['text']

    # Hashes: the same as hashing the text yourself
    snap = _call(client, api_key, 'get_snapshot', watch=uuid, timestamp=T0 + 100)['structuredContent']
    assert snap['sha256'] == hashlib.sha256(w.get_history_snapshot(timestamp=str(T0 + 100)).encode()).hexdigest()
    hist = _call(client, api_key, 'get_history', watch=uuid, timestamps=[T0, T0 + 100])['structuredContent']
    assert hist['patches'][0]['sha256'] == snap['sha256'] and len(hist['base']['sha256']) == 64

    delete_all_watches(client)


def test_mcp_recheck_wait(client, live_server, measure_memory_usage, datastore_path):
    """recheck_watches wait=true: waits for the check and says how it went, instead of 'look later'."""
    from flask import url_for
    datastore = client.application.config['DATASTORE']
    api_key = new_mcp_token(client)
    with open(os.path.join(datastore_path, 'endpoint-content.txt'), 'w') as f:
        f.write('<html><body>Hello there</body></html>')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'title': 'Endpoint'})

    result = _call(client, api_key, 'recheck_watches', watches=[uuid], wait=True, wait_seconds=30)
    assert not result['isError'], result
    check = result['structuredContent']['checks'][0]
    assert check['state'] == 'checked', result['content'][0]['text']
    assert '1 of 1 checked' in result['content'][0]['text']
    # Without wait: the old answer
    assert 'wait=true' in _call(client, api_key, 'recheck_watches', watches=[uuid])['content'][0]['text']
    delete_all_watches(client)


def test_queue_positions():
    """The queue's order for 'queued, position 2 of 3': lowest priority value first."""
    from changedetectionio import queuedWatchMetaData
    from changedetectionio.queue_handlers import RecheckPriorityQueue
    q = RecheckPriorityQueue()
    for uuid, priority in (('a', 5), ('b', 1), ('c', 3)):
        q.put(queuedWatchMetaData.PrioritizedItem(priority=priority, item={'uuid': uuid}))
    assert q.get_queue_positions() == {'b': 1, 'c': 2, 'a': 3}
