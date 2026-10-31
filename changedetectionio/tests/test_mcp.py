#!/usr/bin/env python3
"""The MCP server at /mcp: stateless JSON-RPC, API-key auth, read-only tools."""
import json

from mcp_types.version import LATEST_HANDSHAKE_VERSION
from changedetectionio.blueprint.mcp.tools import UNTRUSTED_NOTE
from .util import delete_all_watches

T0 = 1700000000  # 2023-11-14T22:13:20Z


def _rpc(client, method, params=None, msg_id=1, headers=None, api_key=None):
    body = {'jsonrpc': '2.0', 'method': method}
    if params is not None:
        body['params'] = params
    if msg_id is not None:
        body['id'] = msg_id
    h = {'x-api-key': api_key} if api_key else {}
    h.update(headers or {})
    return client.post('/mcp', data=json.dumps(body), content_type='application/json', headers=h)


def _call(client, api_key, tool, **arguments):
    res = _rpc(client, 'tools/call', {'name': tool, 'arguments': arguments}, api_key=api_key)
    assert res.status_code == 200, res.data
    return res.json['result']


def _setup(datastore):
    group = datastore.add_tag('competitors')
    policy = datastore.add_watch(url='https://example.com/privacy',
                                 extras={'title': 'Privacy Policy', 'paused': True, 'tags': [group]})
    w = datastore.data['watching'][policy]
    w.save_history_blob('Intro\nWe may share data with\nour payment processor.\nOutro', T0, 'a')
    w.save_history_blob('Intro\nWe may share data with\nour payment processor and advertising partners.\nOutro', T0 + 100, 'b')
    broken = datastore.add_watch(url='https://example.com/broken', extras={'title': 'Broken page', 'paused': True})
    datastore.data['watching'][broken]['last_error'] = 'Connection refused'
    return group, policy, broken


def test_mcp_protocol(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('mcp_access_token')

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
                 'get_system_info', 'list_notifications'}
    # update_* can replace settings (e.g. the whole notification URL list), so they count as destructive too
    destructive = {'delete_watch', 'clear_history', 'delete_tag', 'remove_notification', 'update_watch', 'update_tag'}
    assert read_only | destructive <= set(tools)
    assert all(t['inputSchema']['type'] == 'object' for t in tools.values())
    assert {n for n, t in tools.items() if t['annotations']['readOnlyHint']} == read_only
    assert {n for n, t in tools.items() if t['annotations']['destructiveHint']} == destructive
    assert tools['get_changes']['inputSchema']['required'] == ['from']

    # ?readonly=1 offers only the read-only tools, and refuses the others even when called by name, as a tool error
    # the assistant can read and pass on
    res = client.post('/mcp?readonly=1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}),
                      content_type='application/json', headers={'x-api-key': api_key})
    assert {t['name'] for t in res.json['result']['tools']} == read_only
    # Tools that make the server fetch outside pages say so
    assert all(tools[n]['annotations']['openWorldHint'] for n in ('create_watch', 'import_watches', 'recheck_watches'))
    assert all(t['annotations'].get('title') for t in tools.values())
    res = client.post('/mcp?readonly=1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
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
    res = client.post('/mcp', data=json.dumps([{'jsonrpc': '2.0', 'id': 1, 'method': 'ping'},
                                               {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                                               {'jsonrpc': '2.0', 'id': 2, 'method': 'ping'}]),
                      content_type='application/json', headers={'x-api-key': api_key})
    assert [m['id'] for m in res.json] == [1, 2]

    # Errors
    assert _rpc(client, 'resources/list', api_key=api_key).json['error']['code'] == -32601
    res = _rpc(client, 'tools/call', {'name': 'delete_everything', 'arguments': {}}, api_key=api_key)
    assert res.json['error']['code'] == -32602
    res = client.post('/mcp', data='{not json', content_type='application/json', headers={'x-api-key': api_key})
    assert res.status_code == 400 and res.json['error']['code'] == -32700
    assert client.post('/mcp', data=json.dumps({'id': 1}), content_type='application/json',
                       headers={'x-api-key': api_key}).json['error']['code'] == -32600
    # Stateless: no SSE stream, no session
    assert client.get('/mcp').status_code == 405
    assert client.delete('/mcp', headers={'x-api-key': api_key}).status_code == 405


def test_mcp_auth(client, live_server, measure_memory_usage, datastore_path):
    """MCP has its own access token, separate from the REST API key, and it is always required."""
    datastore = client.application.config['DATASTORE']
    settings = datastore.data['settings']['application']
    token = settings.get('mcp_access_token')
    assert token and token != settings.get('api_access_token')

    assert _rpc(client, 'ping').status_code == 403
    assert _rpc(client, 'ping', api_key='wrong').status_code == 403
    # The REST API key is not an MCP token
    assert _rpc(client, 'ping', api_key=settings.get('api_access_token')).status_code == 403
    assert _rpc(client, 'ping', headers={'Authorization': f'Bearer {settings.get("api_access_token")}'}).status_code == 403
    # Bearer (what the copyable configs use) or x-api-key
    assert _rpc(client, 'ping', headers={'Authorization': f'Bearer {token}'}).status_code == 200
    assert _rpc(client, 'ping', api_key=token).status_code == 200
    # A web page in someone's browser must not reach it (DNS rebinding), the assistant itself sends no Origin
    assert _rpc(client, 'ping', api_key=token, headers={'Origin': 'https://evil.example'}).status_code == 403
    from urllib.parse import urlsplit
    from flask import url_for
    own = urlsplit(url_for('mcp.endpoint', _external=True))
    assert _rpc(client, 'ping', api_key=token, headers={'Origin': f'{own.scheme}://{own.netloc}'}).status_code == 200

    # Required even with "API access requires key" off, there is no open mode
    settings['api_access_token_enabled'] = False
    try:
        assert _rpc(client, 'ping').status_code == 403
        # and a password-protected UI never sends an assistant to the login page
        settings['password'] = 'something'
        assert _rpc(client, 'ping', api_key=token).status_code == 200
    finally:
        settings['password'] = False
        settings['api_access_token_enabled'] = True


def test_mcp_tools(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    api_key = datastore.data['settings']['application'].get('mcp_access_token')
    group, policy, broken = _setup(datastore)

    result = _call(client, api_key, 'list_watches')
    assert result['isError'] is False and result['structuredContent']['total'] == 2
    text = result['content'][0]['text']
    assert f'Privacy Policy | https://example.com/privacy | uuid {policy}' in text
    assert 'tags: competitors' in text and 'error: Connection refused' in text
    assert [w['uuid'] for w in _call(client, api_key, 'list_watches', with_errors=True)['structuredContent']['watches']] == [broken]
    assert _call(client, api_key, 'list_watches', tag='competitors')['structuredContent']['total'] == 1
    assert _call(client, api_key, 'list_watches', search='broken')['structuredContent']['total'] == 1
    assert _call(client, api_key, 'list_watches', tag='nope')['isError'] is True

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
    ambiguous = _call(client, api_key, 'get_watch', watch='example.com')
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
    api_key = datastore.data['settings']['application'].get('mcp_access_token')
    watching = datastore.data['watching']

    # Create, with validation shared with the REST API
    result = _call(client, api_key, 'create_watch', url='https://example.com/new-page', title='New page',
                   tags=['Shops'], check_interval={'hours': 6})
    assert result['isError'] is False
    new = result['structuredContent']['uuid']
    assert watching[new]['time_between_check']['hours'] == 6 and result['structuredContent']['tags'] == ['Shops']
    bad = _call(client, api_key, 'create_watch', url='javascript:alert(1)')
    assert bad['isError'] is True and 'Invalid or unsupported URL' in bad['content'][0]['text']

    # Import, capped per call
    result = _call(client, api_key, 'import_watches', urls=['https://example.com/a', 'https://example.com/b', 'ftp:/nope'],
                   tags=['Bulk'])
    assert len(result['structuredContent']['created']) == 2 and len(result['structuredContent']['failed']) == 1
    too_many = _call(client, api_key, 'import_watches', urls=[f'https://example.com/{i}' for i in range(101)])
    assert too_many['isError'] is True and 'At most 100' in too_many['content'][0]['text']

    # Update by name: pause, mute, interval; unknown/invalid values come back as errors
    result = _call(client, api_key, 'update_watch', watch='new-page', paused=True, notification_muted=True,
                   include_filters=['#price'])
    assert result['isError'] is False
    assert watching[new]['paused'] and watching[new]['notification_muted'] and watching[new]['include_filters'] == ['#price']
    assert _call(client, api_key, 'update_watch', watch=new, url='javascript:alert(1)')['isError'] is True
    assert _call(client, api_key, 'update_watch', watch=new)['isError'] is True  # nothing to change

    # Tags by name, created when missing
    result = _call(client, api_key, 'add_tags', watches=[new, 'example.com/a'], tags=['Competitors', 'Shops'])
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
    assert _call(client, api_key, 'delete_watch', watch='example.com')['isError'] is True  # ambiguous
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
    api_key = datastore.data['settings']['application'].get('mcp_access_token')
    uuid = datastore.add_watch(url='https://example.com/validate', extras={'paused': False})

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
