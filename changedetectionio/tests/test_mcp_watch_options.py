#!/usr/bin/env python3
"""MCP: the rest of a monitor's settings (browser steps, conditions, llm_intent, notification templates, JavaScript),
tag auto-apply, send_test_notification, word diffs and HTML snapshots, and the grid rows that guard them."""
import json
import os

import pytest
from flask import url_for
from .util import new_mcp_token, wait_for_notification_endpoint_output

T0 = 1700000000


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    settings = client.application.config['DATASTORE'].data['settings']['application']
    settings['mcp_enabled'] = True
    settings.pop('mcp_tokens', None)
    yield
    settings.pop('mcp_tokens', None)


def _url(name):
    return url_for('test_endpoint', _external=True, id=name)


def _rpc(client, token, method, params=None):
    return client.post('/mcp/v1', data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def _call(client, token, tool, **arguments):
    res = _rpc(client, token, 'tools/call', {'name': tool, 'arguments': arguments})
    assert res.status_code == 200, res.data
    return res.json['result']


def _tools(client, token):
    return {t['name']: t for t in _rpc(client, token, 'tools/list').json['result']['tools']}


def test_mcp_watch_settings(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    token = new_mcp_token(client)

    result = _call(client, token, 'create_watch', url=_url('tickets'), paused=True,
                   browser_steps=[{'operation': 'Click element', 'selector': '#accept-cookies'},
                                  {'operation': 'Wait for seconds', 'optional_value': 2},
                                  {'operation': 'Enter text in field', 'selector': '#q', 'optional_value': 'Sydney'}],
                   conditions=[{'field': 'extracted_number', 'operator': '<', 'value': 450}],
                   conditions_match_logic='ANY', llm_intent='Only when Sydney tour dates are announced',
                   webdriver_delay=3, webdriver_js_execute_code='document.querySelector(".popup")?.remove()',
                   notification_title='{{watch_title}} changed', notification_format='markdown')
    assert not result['isError'], result
    text = result['content'][0]['text']
    # Saved, but the assistant is told why they won't do anything yet
    assert 'browser steps only run with a browser fetcher' in text
    assert "AI isn't set up" in text
    watch = datastore.data['watching'][result['structuredContent']['uuid']]
    assert watch['browser_steps'] == [{'operation': 'Click element', 'selector': '#accept-cookies', 'optional_value': ''},
                                      {'operation': 'Wait for seconds', 'selector': '', 'optional_value': '2'},
                                      {'operation': 'Enter text in field', 'selector': '#q', 'optional_value': 'Sydney'}]
    assert watch['conditions'] == [{'field': 'extracted_number', 'operator': '<', 'value': '450'}]
    assert watch['conditions_match_logic'] == 'ANY' and watch['webdriver_delay'] == 3
    assert watch['llm_intent'] == 'Only when Sydney tour dates are announced'
    assert watch['notification_title'] == '{{watch_title}} changed' and watch['notification_format'] == 'markdown'

    # Read back as they're given
    info = _call(client, token, 'get_watch', watch=watch['uuid'])['structuredContent']
    assert info['browser_steps'][0] == {'operation': 'Click element', 'selector': '#accept-cookies', 'optional_value': ''}
    assert info['conditions'][0]['value'] == '450' and info['llm_intent'] and info['webdriver_delay'] == 3

    # Every step is checked the way it will run, naming the step, and nothing is saved
    for steps, message in (
            ([{'operation': 'Click element'}], "step 1 (Click element): needs a 'selector'"),
            ([{'operation': 'Press Enter', 'selector': '#x'}], "step 1 (Press Enter): takes no 'selector'"),
            ([{'operation': 'Click X,Y', 'optional_value': 'left'}], "'X,Y' in pixels"),
            ([{'operation': 'Wait for seconds', 'optional_value': '600'}], 'at most 60 seconds'),
            ([{'operation': 'Goto URL', 'optional_value': 'file:///etc/passwd'}], 'http(s) URL it may open'),
            ([{'operation': 'Enter text in field', 'selector': '#q', 'optional_value': '{{ broken'}], "doesn't render"),
            ([{'operation': 'Press Enter'}] * 21, 'more than 20 items'),
    ):
        result = _call(client, token, 'update_watch', watch=watch['uuid'], browser_steps=steps)
        assert result['isError'] and message in result['content'][0]['text'], (steps, result)
    assert len(watch['browser_steps']) == 3
    # Unknown operations and keys are already refused by the tool's schema
    result = _call(client, token, 'update_watch', watch=watch['uuid'], browser_steps=[{'operation': 'Hack the planet'}])
    assert result['isError'] and 'Invalid arguments' in result['content'][0]['text']
    result = _call(client, token, 'update_watch', watch=watch['uuid'],
                   browser_steps=[{'operation': 'Press Enter', 'value': 'x'}])
    assert result['isError'] and 'unknown argument' in result['content'][0]['text']

    for conditions, message in (
            ([{'field': 'page_filtered_text', 'operator': 'contains_regex', 'value': '(unclosed'}], "isn't a valid regex"),
            ([{'field': 'extracted_number', 'operator': '>', 'value': 'cheap'}], 'must be a number'),
    ):
        result = _call(client, token, 'update_watch', watch=watch['uuid'], conditions=conditions)
        assert result['isError'] and message in result['content'][0]['text'], result
    result = _call(client, token, 'update_watch', watch=watch['uuid'], notification_body='{% if %}')
    assert result['isError'] and "doesn't render" in result['content'][0]['text']

    # [] removes them
    result = _call(client, token, 'update_watch', watch=watch['uuid'], browser_steps=[], conditions=[])
    assert not result['isError'], result
    assert watch['browser_steps'] == [] and watch['conditions'] == []


def test_mcp_permission_rows(client, live_server, measure_memory_usage, datastore_path):
    """Notification settings need Notifications: write, browser steps and JavaScript need Browser: write. Without
    them the arguments aren't offered, and a call with them is refused with the row to change."""
    datastore = client.application.config['DATASTORE']
    token = new_mcp_token(client, notifications='read', browser='none')
    uuid = datastore.add_watch(url=_url('perms'), extras={'paused': True})

    tools = _tools(client, token)
    for name, hidden in (('create_watch', ('browser_steps', 'webdriver_js_execute_code', 'notification_title')),
                         ('update_watch', ('browser_steps', 'notification_body', 'notification_urls')),
                         ('update_tag', ('url_match_pattern', 'notification_title'))):
        properties = tools[name]['inputSchema']['properties']
        assert not set(hidden) & set(properties), name
    assert 'conditions' in tools['update_watch']['inputSchema']['properties']
    assert 'send_test_notification' not in tools

    result = _call(client, token, 'update_watch', watch=uuid, browser_steps=[{'operation': 'Press Enter'}])
    assert result['isError'] and "'Browser steps & JavaScript'" in result['content'][0]['text']
    result = _call(client, token, 'update_watch', watch=uuid, notification_title='x', webdriver_js_execute_code='1')
    text = result['content'][0]['text']
    assert result['isError'] and "'Notifications'" in text and "'Browser steps & JavaScript'" in text
    assert not datastore.data['watching'][uuid].get('webdriver_js_execute_code')
    # The rest of the monitor is still theirs to change
    assert not _call(client, token, 'update_watch', watch=uuid, webdriver_delay=5)['isError']

    write = new_mcp_token(client, name='write')
    assert not _call(client, write, 'update_watch', watch=uuid, browser_steps=[{'operation': 'Press Enter'}])['isError']


def test_mcp_tag_options(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    token = new_mcp_token(client)
    datastore.add_watch(url=_url('shop-one'), extras={'paused': True})
    result = _call(client, token, 'create_tag', title='Shops', url_match_pattern='*shop-*', overrides_watch=True,
                   notification_title='Shop change: {{watch_title}}')
    assert not result['isError'], result
    assert 'applies to 1 more monitors' in result['content'][0]['text']
    tag = datastore.data['settings']['application']['tags'][result['structuredContent']['uuid']]
    assert tag['url_match_pattern'] == '*shop-*' and tag['overrides_watch'] is True

    # A token limited to its groups can't reach monitors outside them through a URL pattern
    limited = new_mcp_token(client, name='limited', tags=[tag['uuid']])
    result = _call(client, limited, 'update_tag', tag='Shops', url_match_pattern='*')
    assert result['isError'] and 'url_match_pattern' in result['content'][0]['text']
    assert tag['url_match_pattern'] == '*shop-*'


def test_mcp_send_test_notification(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    token = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('notify-me'), extras={'title': 'Notify me', 'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('Price 100', T0, 'a')
    watch.save_history_blob('Price 90', T0 + 60, 'b')

    result = _call(client, token, 'send_test_notification', watch=uuid)
    assert result['isError'] and 'add_notification' in result['content'][0]['text']

    endpoint = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')
    watch['notification_urls'] = [endpoint]
    notification_file = os.path.join(datastore_path, 'notification.txt')
    if os.path.isfile(notification_file):
        os.unlink(notification_file)
    result = _call(client, token, 'send_test_notification', watch=uuid,
                   notification_body='TEST {{watch_title}} {{diff_added}}', notification_format='text')
    assert not result['isError'], result
    assert wait_for_notification_endpoint_output(datastore_path=datastore_path)
    with open(notification_file) as f:
        sent = f.read()
    # The template given, with the monitor's latest change as the example
    assert 'TEST Notify me' in sent and '90' in sent and '<span' not in sent

    # A failure says why, without the URL's secrets
    watch['notification_urls'] = ['post://127.0.0.1:1/hook-secret-a8f3k2?token=sekrit99']
    result = _call(client, token, 'send_test_notification', watch=uuid)
    text = result['content'][0]['text']
    assert result['isError'] and 'failed' in text
    assert 'hook-secret-a8f3k2' not in text and 'sekrit99' not in text


def test_mcp_word_diff_and_html(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    token = new_mcp_token(client)
    uuid = datastore.add_watch(url=_url('words'), extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('Intro\nWe may share data with our payment processor.\nOutro', T0, 'a')
    watch.save_history_blob('Intro\nWe may share data with our payment processor and advertisers.\nOutro', T0 + 60, 'b')
    watch.save_last_fetched_html(timestamp=T0 + 60, contents='<html><body><p id="policy">We may share</p></body></html>')

    diff = _call(client, token, 'get_diff', watch=uuid, word_diff=True, context=0)['structuredContent']['diff']
    assert '[-processor.-]' in diff and '{+processor and advertisers.+}' in diff and 'Outro' not in diff

    result = _call(client, token, 'get_snapshot', watch=uuid, html=True)
    assert not result['isError'] and '<p id="policy">' in result['structuredContent']['content']
    result = _call(client, token, 'get_snapshot', watch=uuid, html=True, timestamp=T0)
    assert result['isError'] and 'newest two snapshots' in result['content'][0]['text']


def test_mcp_pause_watches(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    app = datastore.data['settings']['application']
    token = new_mcp_token(client)
    shops = datastore.add_tag('shops')
    a = datastore.add_watch(url=_url('pause-a'), extras={'title': 'Shop A', 'tags': [shops]})
    b = datastore.add_watch(url=_url('pause-b'), extras={'title': 'Shop B', 'tags': [shops]})
    c = datastore.add_watch(url=_url('pause-c'), extras={'title': 'News', 'paused': True})
    watching = datastore.data['watching']
    try:
        # A whole group, then again (nothing to do)
        result = _call(client, token, 'pause_watches', tag='shops', paused=True)
        assert not result['isError'] and watching[a]['paused'] and watching[b]['paused'] and 'Paused 2' in result['content'][0]['text']
        assert 'already were' in _call(client, token, 'pause_watches', tag='shops', paused=True)['content'][0]['text']
        # One by name, and all
        _call(client, token, 'pause_watches', watches=['Shop A'], paused=False)
        assert not watching[a]['paused'] and watching[b]['paused']
        _call(client, token, 'pause_watches', all=True, paused=False)
        assert not any(watching[u]['paused'] for u in (a, b, c))
        assert _call(client, token, 'pause_watches', paused=True)['isError']

        # The whole instance's scheduler, leaving each monitor's own setting alone
        result = _call(client, token, 'pause_watches', scheduler=True, paused=True)
        assert not result['isError'] and app['all_paused'] is True and not watching[a]['paused']
        assert 'whole instance' in _call(client, token, 'pause_watches', watches=[a], paused=False)['content'][0]['text']
        assert _call(client, token, 'pause_watches', scheduler=True, tag='shops', paused=False)['isError']
        _call(client, token, 'pause_watches', scheduler=True, paused=False)
        assert app['all_paused'] is False

        # A token limited to a group: only its monitors, and never the whole instance
        limited = new_mcp_token(client, name='limited', tags=[shops])
        result = _call(client, limited, 'pause_watches', all=True, paused=True)
        assert 'Paused 2' in result['content'][0]['text'] and watching[a]['paused'] and not watching[c]['paused']
        result = _call(client, limited, 'pause_watches', scheduler=True, paused=True)
        assert result['isError'] and not app.get('all_paused')
    finally:
        app['all_paused'] = False
