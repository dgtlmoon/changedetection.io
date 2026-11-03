#!/usr/bin/env python3
"""An MCP access token limited to some tags (groups): it sees, changes and creates only the monitors in them.

The important test is test_every_tool_stays_in_scope: it calls every tool the server offers (core and plugins) with a
monitor and a group outside the token's scope, so a tool added later that forgets the scope fails here."""
import json

import pytest
from .util import delete_all_watches, new_mcp_token

SECRET_URL = 'https://secret.example.com/case-b'
SECRET_TITLE = 'Secret case B page'


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    client.application.config['DATASTORE'].data['settings']['application']['mcp_enabled'] = True


def _call(client, token, tool, **arguments):
    res = client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call',
                                                  'params': {'name': tool, 'arguments': arguments}}),
                      content_type='application/json', headers={'Authorization': f'Bearer {token}'})
    assert res.status_code == 200, res.data
    return res.json['result'] if 'result' in res.json else {'isError': True, 'content': [{'text': json.dumps(res.json)}]}


def _setup(datastore):
    case_a, case_b = datastore.add_tag('case A'), datastore.add_tag('case B')
    mine = datastore.add_watch(url='https://shop.example.com/case-a', extras={'title': 'Case A shop', 'paused': True,
                                                                              'tags': [case_a]})
    both = datastore.add_watch(url='https://forum.example.com/thread', extras={'title': 'Forum thread', 'paused': True,
                                                                               'tags': [case_a, case_b]})
    secret = datastore.add_watch(url=SECRET_URL, extras={'title': SECRET_TITLE, 'paused': True, 'tags': [case_b],
                                                         'processor': 'restock_diff'})
    untagged = datastore.add_watch(url='https://untagged.example.com/', extras={'title': 'Untagged', 'paused': True})
    for uuid in (mine, both, secret, untagged):
        w = datastore.data['watching'][uuid]
        w.save_history_blob('first version', 1700000000, 'a')
        w.save_history_blob('second version', 1700000100, 'b')
    datastore.data['settings']['application']['notification_urls'] = ['json://global.example.com/hook']
    return case_a, case_b, mine, both, secret, untagged


def _arguments(name, schema, secret, case_b):
    """Calls that point at what the token must not reach: the secret monitor, the other group, the global settings."""
    properties = schema['properties']
    filler = {'text': 'version', 'from': '2020-01-01', 'url': 'https://new.example.com/x', 'urls': ['https://new.example.com/y'],
              'title': 'New', 'position': 1, 'tags': ['case B'], 'price_change_min': 1}
    base = {k: v for k, v in filler.items() if k in schema.get('required', [])}
    calls = []
    if 'watch' in properties:
        calls += [dict(base, watch=secret), dict(base, watch='secret.example'), dict(base, watch='Secret case')]
    if 'watches' in properties:
        calls.append(dict(base, watches=[secret]))
    if 'tag' in properties:
        calls.append(dict(base, tag='case B'))
        calls.append(dict(base, tag=case_b))
    if 'tags' in properties:
        calls.append(dict(base, tags=['case B'], **({'watches': [secret]} if 'watches' in properties else {})))
    if not schema.get('required') or set(schema['required']) <= set(base):
        calls.append(dict(base))
    if name == 'recheck_watches':
        calls += [{'all': True}, {'with_errors': True}]
    return calls


def test_every_tool_stays_in_scope(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.blueprint.mcp.tools import definitions
    datastore = client.application.config['DATASTORE']
    case_a, case_b, mine, both, secret, untagged = _setup(datastore)
    token = new_mcp_token(client, tags=[case_a])

    tried = 0
    for tool in definitions():
        name, schema = tool['name'], tool['inputSchema']
        for arguments in _arguments(name, schema, secret, case_b):
            result = _call(client, token, name, **arguments)
            text = json.dumps(result)
            tried += 1
            # Whatever the tool did, nothing about the other group's monitor comes back...
            assert SECRET_URL not in text and SECRET_TITLE not in text, (name, arguments, text[:500])
            assert 'untagged.example.com' not in text, (name, arguments, text[:500])
            if arguments.get('watch') == secret or arguments.get('watches') == [secret]:
                # ...and a uuid outside the scope is "not found", as if it didn't exist
                assert result['isError'], (name, arguments, text[:500])
            assert 'global.example.com' not in text, (name, arguments, text[:500])
    assert tried > 60, "every tool, several ways"

    # ...and nothing outside the scope was changed
    w = datastore.data['watching'].get(secret)
    assert w is not None and len(w.history) == 2 and w.get('tags') == [case_b] and w.get('paused')
    assert datastore.data['watching'][untagged].get('tags') == []
    assert case_b in datastore.data['settings']['application']['tags']
    assert datastore.data['settings']['application']['notification_urls'] == ['json://global.example.com/hook']
    assert not any('case B' in str(w.get('tags')) for w in datastore.data['watching'].values()
                   if w.get('url', '').startswith('https://new.example.com'))
    delete_all_watches(client)


def test_limited_token_works_inside_its_groups(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    case_a, case_b, mine, both, secret, untagged = _setup(datastore)
    token = new_mcp_token(client, tags=[case_a])

    # Sees its groups' monitors (one tagged with both groups too), and only its own groups' names
    listed = _call(client, token, 'list_watches')['structuredContent']
    assert sorted(w['title'] for w in listed['watches']) == ['Case A shop', 'Forum thread'] and listed['total'] == 2
    assert next(w for w in listed['watches'] if w['title'] == 'Forum thread')['tags'] == ['case A']
    assert [t['title'] for t in _call(client, token, 'list_tags')['structuredContent']['tags']] == ['case A']
    info = _call(client, token, 'get_system_info')['structuredContent']
    assert info['watch_count'] == 2 and info['tag_count'] == 1 and info['limited_to_groups'] == ['case A']
    assert _call(client, token, 'get_changes', **{'from': '2023-01-01'})['structuredContent']['total'] == 2

    # A new monitor goes in its group (the only one, so without saying)
    created = _call(client, token, 'create_watch', url='https://new.example.com/a')
    assert not created['isError'], created
    assert created['structuredContent']['tags'] == ['case A']
    assert datastore.data['watching'][created['structuredContent']['uuid']].get('tags') == [case_a]

    # Can't take a monitor out of its last group, can't create or delete groups, can't touch global notifications
    result = _call(client, token, 'remove_tags', watches=[mine], tags=['case A'])
    assert result['isError'] and 'out of every group' in result['content'][0]['text']
    for tool, arguments in (('create_tag', {'title': 'case C'}), ('delete_tag', {'tag': 'case A'}),
                            ('list_notifications', {})):
        result = _call(client, token, tool, **arguments)
        assert result['isError'] and 'limited to the groups case A' in result['content'][0]['text'], (tool, result)
    assert not _call(client, token, 'list_notifications', tag='case A')['isError']

    # The assistant is told when it connects
    res = client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
        'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}}),
                      content_type='application/json', headers={'Authorization': f'Bearer {token}'})
    assert 'limited to the monitors in the groups case A' in res.json['result']['instructions']

    # Several groups: a new monitor needs to say which; a token whose groups were all deleted sees nothing
    token2 = new_mcp_token(client, tags=[case_a, case_b])
    result = _call(client, token2, 'create_watch', url='https://new.example.com/b')
    assert result['isError'] and "say which one" in result['content'][0]['text']
    assert not _call(client, token2, 'create_watch', url='https://new.example.com/b', tags=['case B'])['isError']
    token3 = new_mcp_token(client, tags=['deleted-tag-uuid'])
    assert _call(client, token3, 'list_watches')['structuredContent']['total'] == 0

    # An unlimited token still sees everything
    assert _call(client, new_mcp_token(client), 'list_watches')['structuredContent']['total'] == 6
    delete_all_watches(client)


def test_token_groups_in_the_settings_page(client, live_server, measure_memory_usage, datastore_path):
    """The token overlay's group checkboxes: saved on add and on edit, shown on the token list."""
    datastore = client.application.config['DATASTORE']
    case_a = datastore.add_tag('case A')
    page = client.get('/settings/ai/mcp')
    assert b'Only these groups' in page.data and case_a.encode() in page.data

    res = client.post('/settings/ai/mcp/tokens', data={'name': 'case A analyst', 'perm_monitors': 'read',
                                                       'perm_tags': 'read', 'perm_notifications': 'none',
                                                       'perm_system': 'read', 'tags': [case_a]})
    assert res.status_code == 200, res.data
    token_id = res.json['id']
    stored = datastore.data['settings']['application']['mcp_tokens'][token_id]
    assert stored['tags'] == [case_a]
    assert 'Only' in res.json['html'] and 'case A' in res.json['html']
    # A tag that doesn't exist is refused, unticking all is "every monitor"
    bad = client.post(f'/settings/ai/mcp/tokens/{token_id}', data={'name': 'x', 'perm_monitors': 'read', 'perm_tags': 'read',
                                                                    'perm_notifications': 'none', 'perm_system': 'read',
                                                                    'tags': ['nope']})
    assert bad.status_code == 400
    client.post(f'/settings/ai/mcp/tokens/{token_id}', data={'name': 'x', 'perm_monitors': 'read', 'perm_tags': 'read',
                                                              'perm_notifications': 'none', 'perm_system': 'read'})
    assert stored['tags'] == []
