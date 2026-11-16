#!/usr/bin/env python3
"""MCP tools from plugins (the register_mcp_tools hook), and the built-in restock_diff ones."""
import json

import pytest
from changedetectionio.pluggy_interface import hookimpl, plugin_manager
from .util import delete_all_watches, new_mcp_token


@pytest.fixture(autouse=True)
def mcp_switched_on(client):
    """The MCP server is off until the switch on its settings tab is on, these tests are about it being on."""
    client.application.config['DATASTORE'].data['settings']['application']['mcp_enabled'] = True
    client.application.config['MCP_TEST_TOKEN'] = new_mcp_token(client)


def _rpc(client, method, params=None, read_only=False):
    token = client.application.config['MCP_TEST_TOKEN']
    return client.post('/mcp/v1' + ('?readonly=1' if read_only else ''),
                       data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params or {}}),
                       content_type='application/json', headers={'Authorization': f'Bearer {token}'})


def _call(client, tool, **arguments):
    res = _rpc(client, 'tools/call', {'name': tool, 'arguments': arguments})
    assert res.status_code == 200, res.data
    return res.json['result']


def _tools(client, read_only=False):
    return {t['name']: t for t in _rpc(client, 'tools/list', read_only=read_only).json['result']['tools']}


def _product(datastore, title, in_stock, price, tags=None):
    uuid = datastore.add_watch(url=f'https://shop.example.com/{title.lower().replace(" ", "-")}',
                               extras={'title': title, 'processor': 'restock_diff', 'paused': True, 'tags': tags or []})
    datastore.data['watching'][uuid]['restock'] = {'in_stock': in_stock, 'price': price, 'currency': 'AUD'}
    return uuid


def test_restock_tools(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    wishlist = datastore.add_tag('wishlist')
    headphones = _product(datastore, 'Sony WH-1000XM6', True, 429.0, [wishlist])
    camera = _product(datastore, 'Fuji X100VI', False, 2799.0, [wishlist])
    _product(datastore, 'Kettle', True, 79.0)
    page = datastore.add_watch(url='https://example.com/news', extras={'title': 'News page', 'paused': True})

    # Listed next to core's tools, with annotations from their kind; the read-only ones only in read-only mode
    tools = _tools(client)
    assert tools['restock_status']['annotations']['readOnlyHint'] is True
    assert tools['restock_set_rules']['annotations']['readOnlyHint'] is False
    assert tools['restock_set_rules']['inputSchema']['required'] == ['watch']
    read_only_tools = _tools(client, read_only=True)
    assert 'restock_status' in read_only_tools and 'restock_set_rules' not in read_only_tools

    # "What on my wishlist is back in stock?"
    result = _call(client, 'restock_status', tag='wishlist', in_stock=True)
    assert result['isError'] is False
    assert [m['title'] for m in result['structuredContent']['monitors']] == ['Sony WH-1000XM6']
    assert 'Sony WH-1000XM6 | in stock, 429.0 AUD' in result['content'][0]['text']
    everything = _call(client, 'restock_status')['structuredContent']
    assert everything['total'] == 3, "only restock_diff monitors, not the news page"

    # "Is anything cheap now?": a name search, and the price history from the snapshots, as on the price graph
    t0 = 1700000000
    for i, (stock, price) in enumerate([(True, 449.0), (True, 379.0), (True, 399.0), (True, 429.0), (True, 429.0)]):
        datastore.data['watching'][headphones].save_history_blob(f"In Stock: {stock} - Price: {price}", t0 + i * 86400, str(i))
    result = _call(client, 'restock_status', search='sony')
    monitors = result['structuredContent']['monitors']
    assert [m['title'] for m in monitors] == ['Sony WH-1000XM6'], "search matches the title or URL"
    history = monitors[0]['price_history']
    assert (history['min'], history['max'], history['snapshots']) == (379.0, 449.0, 5)
    assert history['last_change'] == {'from': 399.0, 'to': 429.0, 'date': '2023-11-17T22:13:20Z'}
    assert history['since'] == '2023-11-17T22:13:20Z', "the start of the run at the current price"
    assert 'was 399.0 until 2023-11-17' in result['content'][0]['text']
    assert _call(client, 'restock_status', search='kettle')['structuredContent']['monitors'][0]['price_history'] is None, \
        "no snapshots yet, no history"
    assert _call(client, 'restock_status', search='nothing like it')['structuredContent']['total'] == 0

    # "Tell me if it goes under $450": only the rules given change, the others are kept
    result = _call(client, 'restock_set_rules', watch='Sony', in_stock_processing='in_stock_only')
    assert result['isError'] is False, result
    result = _call(client, 'restock_set_rules', watch=headphones, price_change_min=450)
    assert result['isError'] is False, result
    rules = result['structuredContent']['rules']
    assert rules['price_change_min'] == 450 and rules['in_stock_processing'] == 'in_stock_only'
    # Saved where the processor reads it, and shown by get_watch like the REST API does
    info = _call(client, 'get_watch', watch=headphones)['structuredContent']
    assert info['processor_config_restock_diff']['price_change_min'] == 450
    assert info['processor_state_restock_diff']['in_stock'] is True
    # null removes a limit
    assert 'price_change_min' not in [k for k, v in _call(client, 'restock_set_rules', watch=headphones,
                                       price_change_min=None)['structuredContent']['rules'].items() if v is not None]

    # Mistakes come back as errors the assistant can read and fix
    assert 'price_change_min (500' in _call(client, 'restock_set_rules', watch=camera, price_change_min=500,
                                            price_change_max=100)['content'][0]['text']
    result = _call(client, 'restock_set_rules', watch=camera, in_stock_processing='sometimes')
    assert result['isError'] is True and 'in_stock_processing' in result['content'][0]['text']
    result = _call(client, 'restock_set_rules', watch=camera, colour='red')
    assert result['isError'] is True and 'unknown argument' in result['content'][0]['text']
    result = _call(client, 'restock_set_rules', watch=camera)
    assert result['isError'] is True and 'Nothing to change' in result['content'][0]['text']
    # Core refuses monitors that use another processor, before the plugin runs
    result = _call(client, 'restock_set_rules', watch=page, price_change_min=10)
    assert result['isError'] is True
    assert "only works on restock_diff monitors, 'News page' uses text_json_diff" in result['content'][0]['text']

    # A tag that overrides its monitors' settings: saving the monitor's own rules would do nothing, so it says so
    tags = datastore.data['settings']['application']['tags']
    tags[wishlist]['overrides_watch'] = True
    tags[wishlist]['processor_config_restock_diff'] = {'in_stock_processing': 'all_changes'}
    result = _call(client, 'restock_set_rules', watch=camera, price_change_min=2000)
    assert result['isError'] is True and "from the tag 'wishlist'" in result['content'][0]['text']
    tags[wishlist]['overrides_watch'] = False

    # Read-only mode refuses the write one even when called directly
    res = _rpc(client, 'tools/call', {'name': 'restock_set_rules', 'arguments': {'watch': camera, 'price_change_min': 1}},
               read_only=True)
    assert res.json['result']['isError'] is True and 'read-only' in res.json['result']['content'][0]['text']

    delete_all_watches(client)


class _ThirdPartyPlugin:
    """A plugin's tools: one good, and the kinds of mistakes core must skip rather than offer."""

    @staticmethod
    def handler(ctx, args, watch):
        return 'x' * 200_000, {'watch': watch.get('uuid') if watch else None}

    @hookimpl
    def register_mcp_tools(self):
        good = {'title': 'Example', 'description': 'An example tool', 'kind': 'read', 'handler': self.handler,
                'input_schema': {'watch': {'type': 'string'}}}
        return [dict(good, name='example_long_answer'),
                dict(good, name='list_watches'),          # core's
                dict(good, name='Bad-Name'),
                dict(good, name='example_no_kind', kind='sometimes'),
                dict(good, name='example_no_handler', handler=None)]


def test_plugin_tool_rules(client, live_server, measure_memory_usage, datastore_path):
    plugin = _ThirdPartyPlugin()
    plugin_manager.register(plugin, 'test_mcp_third_party')
    try:
        tools = _tools(client)
        assert 'example_long_answer' in tools
        for skipped in ('Bad-Name', 'example_no_kind', 'example_no_handler'):
            assert skipped not in tools
        assert tools['list_watches']['title'] == 'List monitors', "a plugin can't replace a core tool"

        datastore = client.application.config['DATASTORE']
        uuid = datastore.add_watch(url='https://example.com/a', extras={'title': 'Page A', 'paused': True})
        result = _call(client, 'example_long_answer', watch='Page A')
        assert result['isError'] is False
        assert result['structuredContent'] == {'watch': uuid}, "the watch argument is resolved by core"
        assert len(result['content'][0]['text']) < 101_000 and result['content'][0]['text'].endswith('characters')
    finally:
        plugin_manager.unregister(plugin)
    assert 'example_long_answer' not in _tools(client), "gone with the plugin"
    delete_all_watches(client)


class _AccountPlugin:
    """A plugin with its own permission row, like a sign-up tool on a demo: not about monitors at all."""

    @hookimpl
    def register_mcp_permission_rows(self):
        return [{'name': 'account', 'label': 'Account & billing', 'description': 'Write: start a subscription.'},
                {'name': 'unused', 'label': 'No tool uses this'},
                {'name': 'monitors', 'label': "Core's name, refused"}]

    @hookimpl
    def register_mcp_tools(self):
        return [{'name': 'example_signup', 'title': 'Start a subscription', 'kind': 'write', 'area': 'account',
                 'open_world': True, 'description': 'A checkout link for a new account.',
                 'input_schema': {'account': {'type': 'string'}}, 'required': ['account'],
                 'handler': lambda ctx, args, watch: (f"https://pay.example.com/{args['account']}", {'ok': True})},
                {'name': 'example_bad_area', 'title': 'Bad', 'kind': 'read', 'area': 'nowhere', 'description': 'x',
                 'handler': lambda ctx, args, watch: ('', {})},
                {'name': 'example_system_write', 'title': 'Bad', 'kind': 'write', 'area': 'system', 'description': 'x',
                 'handler': lambda ctx, args, watch: ('', {})}]


def test_plugin_permission_rows(client, live_server, measure_memory_usage, datastore_path):
    from flask import url_for
    from changedetectionio.blueprint.mcp import tools as mcp_tools
    plugin = _AccountPlugin()
    plugin_manager.register(plugin, 'test_mcp_account')
    try:
        rows = mcp_tools.plugin_permission_rows()
        assert list(rows) == ['account'], "a row no tool uses, and a core row's name, are left out"
        assert rows['account']['levels'] == ('none', 'write'), "only the levels its tools need"
        assert 'example_bad_area' not in mcp_tools.get_tools() and 'example_system_write' not in mcp_tools.get_tools()

        # A token from before the row existed, or one left at the default: None, even with everything else at write
        assert _call(client, 'example_signup', account='acme')['isError'] is True
        assert 'example_signup' not in _tools(client)
        refused = _call(client, 'example_signup', account='acme')['content'][0]['text']
        assert "'Account & billing'" in refused

        # Read on monitors, Write on the plugin's row: the demo case
        settings = client.application.config['DATASTORE'].data['settings']['application']
        client.application.config['MCP_TEST_TOKEN'] = new_mcp_token(client, monitors='read', tags='read', account='write')
        listed = _tools(client)
        assert 'example_signup' in listed and 'create_watch' not in listed
        assert listed['example_signup']['annotations']['openWorldHint'] is True
        assert listed['example_signup']['annotations']['readOnlyHint'] is False
        result = _call(client, 'example_signup', account='acme')
        assert result['isError'] is False and result['content'][0]['text'] == 'https://pay.example.com/acme'
        assert 'example_signup' not in _tools(client, read_only=True), "?readonly=1 still caps it"

        # The grid and the token list show the row
        html = client.get(url_for('settings.llm.mcp_settings_page')).get_data(as_text=True)
        assert 'Account &amp; billing' in html and 'name="perm_account"' in html and 'Write: start a subscription.' in html
        res = client.post(url_for('settings.llm.mcp_token_add'), data={'name': 'with account', 'perm_monitors': 'read',
                          'perm_tags': 'read', 'perm_notifications': 'none', 'perm_browser': 'none',
                          'perm_system': 'none', 'perm_account': 'write'})
        assert res.status_code == 200, res.data
        saved = [t for t in settings['mcp_tokens'].values() if t['name'] == 'with account'][0]
        assert saved['permissions']['account'] == 'write'
        token_list = ''.join(v for v in res.json.values() if isinstance(v, str))
        assert 'Account &amp; billing <strong>' in token_list
        assert 'Browser steps &amp; JavaScript <strong>' in token_list, "core's browser row has its label in the list too"
    finally:
        plugin_manager.unregister(plugin)
        client.application.config['MCP_TEST_TOKEN'] = new_mcp_token(client)
    assert 'account' not in mcp_tools.plugin_permission_rows(), "gone with the plugin"
