"""
Tests for the LLM restock fallback plugin.

All LLM calls are mocked — no real API key required.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _clear_llm_result_cache():
    """The plugin keeps a module-level result cache (keyed by model+prompt) so it won't
    re-bill the LLM when the meaningful page content is unchanged. That cache persists
    across tests in the same process, which makes token-accounting assertions order
    dependent (a cache hit returns zeroed tokens). Clear it before every test so each
    one exercises a fresh extraction."""
    from changedetectionio.processors.restock_diff.plugins import llm_restock
    llm_restock._LLM_RESULT_CACHE.clear()
    yield
    llm_restock._LLM_RESULT_CACHE.clear()


def _make_datastore(llm_model='gpt-4o-mini', enabled=True):
    """Minimal datastore mock with the fields the plugin reads."""
    ds = MagicMock()
    ds.data = {
        'settings': {
            'application': {
                'llm': {
                    'enabled': True,
                    'restock_use_fallback_extract': enabled,
                    'model': llm_model,
                    'api_key': 'test-key',
                    'api_base': '',
                    'tokens_total_cumulative': 0,
                    'tokens_this_month': 0,
                    'tokens_month_key': '2099-01',
                    'cost_usd_total_cumulative': 0.0,
                    'cost_usd_this_month': 0.0,
                },
            }
        }
    }
    return ds


def _call_plugin(content, url='https://example.com/product',
                 llm_json=None, datastore=None, enabled=True, llm_intent=None):
    """Helper: import plugin, inject datastore, call the hook, return result."""
    from changedetectionio.processors.restock_diff.plugins import llm_restock

    if datastore is None:
        datastore = _make_datastore(enabled=enabled)
    llm_restock.datastore = datastore

    if llm_json is not None:
        with patch('changedetectionio.llm.client.completion',
                   return_value=(llm_json, 50, 40, 10)):
            return llm_restock.get_itemprop_availability_override(
                content=content,
                fetcher_name='html_requests',
                fetcher_instance=None,
                url=url,
                llm_intent=llm_intent,
            )
    else:
        return llm_restock.get_itemprop_availability_override(
            content=content,
            fetcher_name='html_requests',
            fetcher_instance=None,
            url=url,
            llm_intent=llm_intent,
        )


class TestLLMRestockPluginDisabled:
    def test_returns_none_when_no_datastore(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        llm_restock.datastore = None
        result = llm_restock.get_itemprop_availability_override(
            content='<html><body>Price: $49.99 In Stock</body></html>',
            fetcher_name='html_requests',
            fetcher_instance=None,
            url='https://example.com/product',
            llm_intent=None,
        )
        assert result is None

    def test_returns_none_when_setting_disabled(self):
        result = _call_plugin(
            '<html><body>Price: $49.99 In Stock</body></html>',
            enabled=False,
        )
        assert result is None

    def test_returns_none_when_no_llm_configured(self):
        ds = MagicMock()
        ds.data = {
            'settings': {
                'application': {
                    # No 'llm' key → get_llm_config returns None;
                    # restock_use_fallback_extract still defaults to True via LLMSettings
                }
            }
        }
        result = _call_plugin(
            '<html><body>Price: $49.99 In Stock</body></html>',
            datastore=ds,
        )
        assert result is None

    def test_returns_none_for_empty_content(self):
        result = _call_plugin('', llm_json='{"price": 9.99, "currency": "USD", "availability": "instock"}')
        assert result is None


class TestLLMRestockPluginExtraction:
    def test_extracts_price_and_in_stock(self):
        llm_json = '{"price": 49.99, "currency": "USD", "availability": "instock"}'
        result = _call_plugin(
            '<html><body><span class="price">$49.99</span> <span>In Stock</span></body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 49.99
        assert result['currency'] == 'USD'
        assert result['availability'] == 'instock'

    def test_extracts_out_of_stock(self):
        llm_json = '{"price": 129.00, "currency": "EUR", "availability": "outofstock"}'
        result = _call_plugin(
            '<html><body>129,00 € — Sold out</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 129.0
        assert result['currency'] == 'EUR'
        assert result['availability'] == 'outofstock'

    def test_returns_availability_only_when_no_price(self):
        llm_json = '{"price": null, "currency": null, "availability": "instock"}'
        result = _call_plugin(
            '<html><body>Item available</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] is None
        assert result['availability'] == 'instock'

    def test_returns_price_only_when_no_availability(self):
        llm_json = '{"price": 19.95, "currency": "GBP", "availability": null}'
        result = _call_plugin(
            '<html><body>£19.95</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 19.95
        assert result['availability'] is None

    def test_returns_none_when_both_null(self):
        llm_json = '{"price": null, "currency": null, "availability": null}'
        result = _call_plugin(
            '<html><body>No pricing info here</body></html>',
            llm_json=llm_json,
        )
        assert result is None

    def test_strips_markdown_fences(self):
        llm_json = '```json\n{"price": 9.99, "currency": "USD", "availability": "instock"}\n```'
        result = _call_plugin(
            '<html><body>$9.99 In Stock</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 9.99

    def test_handles_integer_price(self):
        llm_json = '{"price": 100, "currency": "USD", "availability": "instock"}'
        result = _call_plugin(
            '<html><body>$100 In Stock</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 100.0

    def test_handles_string_price(self):
        """Model might return price as a string despite the prompt."""
        llm_json = '{"price": "49.99", "currency": "USD", "availability": "instock"}'
        result = _call_plugin(
            '<html><body>$49.99</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == 49.99

    @pytest.mark.parametrize('price_str, expected', [
        ('1.299,95', 1299.95),
        ('1.299,95 €', 1299.95),
        ('1,299.95', 1299.95),
        ('10 000 Kč', 10000.0),
        ('10 000,50', 10000.5),
        ('$127.99', 127.99),
    ])
    def test_handles_locale_formatted_string_price(self, price_str, expected):
        """A string price in page format must not be mangled by stripping its separators (same as #4493)."""
        llm_json = json.dumps({'price': price_str, 'currency': None, 'availability': 'instock'})
        result = _call_plugin(
            f'<html><body>{price_str}</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['price'] == expected


class TestLLMRestockPluginTokenAccounting:
    def test_result_includes_token_metadata(self):
        """Plugin result must carry _tokens/_input_tokens/_output_tokens/_model."""
        llm_json = '{"price": 49.99, "currency": "USD", "availability": "instock"}'
        result = _call_plugin(
            '<html><body>$49.99 In Stock</body></html>',
            llm_json=llm_json,
        )
        assert result is not None
        assert result['_tokens'] == 50
        assert result['_input_tokens'] == 40
        assert result['_output_tokens'] == 10
        assert result['_model'] == 'gpt-4o-mini'

    def test_token_keys_not_in_none_result(self):
        """When LLM returns nothing useful, result is None — no token metadata leaked."""
        llm_json = '{"price": null, "currency": null, "availability": null}'
        result = _call_plugin(
            '<html><body>No pricing info</body></html>',
            llm_json=llm_json,
        )
        assert result is None


class TestLLMRestockPluginIntent:
    def test_llm_intent_appended_to_user_prompt(self):
        """llm_intent should appear in the prompt sent to the LLM."""
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        ds = _make_datastore()
        llm_restock.datastore = ds

        captured = {}
        def fake_completion(model, messages, api_key, api_base, max_tokens, extra_body=None, timeout=None):
            captured['messages'] = messages
            return ('{"price": 299.0, "currency": "USD", "availability": "instock"}', 50, 40, 10)

        with patch('changedetectionio.llm.client.completion', side_effect=fake_completion):
            result = llm_restock.get_itemprop_availability_override(
                content='<html><body>$299 In Stock</body></html>',
                fetcher_name='html_requests',
                fetcher_instance=None,
                url='https://example.com',
                llm_intent='Alert me when price drops below $300',
            )

        assert result is not None
        user_msg = next(m for m in captured['messages'] if m['role'] == 'user')
        assert 'Alert me when price drops below $300' in user_msg['content']

    def test_no_intent_prompt_unchanged(self):
        """Without llm_intent the user prompt should not include the intent line."""
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        ds = _make_datastore()
        llm_restock.datastore = ds

        captured = {}
        def fake_completion(model, messages, api_key, api_base, max_tokens, extra_body=None, timeout=None):
            captured['messages'] = messages
            return ('{"price": 9.99, "currency": "USD", "availability": "instock"}', 20, 15, 5)

        with patch('changedetectionio.llm.client.completion', side_effect=fake_completion):
            llm_restock.get_itemprop_availability_override(
                content='<html><body>$9.99 In Stock</body></html>',
                fetcher_name='html_requests',
                fetcher_instance=None,
                url='https://example.com',
                llm_intent=None,
            )

        user_msg = next(m for m in captured['messages'] if m['role'] == 'user')
        assert 'notification intent' not in user_msg['content']


class TestLLMRestockPluginErrorHandling:
    def test_returns_none_on_bad_json(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        ds = _make_datastore()
        llm_restock.datastore = ds

        with patch('changedetectionio.llm.client.completion',
                   return_value=('not valid json at all', 10, 8, 2)):
            result = llm_restock.get_itemprop_availability_override(
                content='<html><body>$49.99 In Stock</body></html>',
                fetcher_name='html_requests',
                fetcher_instance=None,
                url='https://example.com',
                llm_intent=None,
            )
        assert result is None

    def test_returns_none_on_llm_exception(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        ds = _make_datastore()
        llm_restock.datastore = ds

        with patch('changedetectionio.llm.client.completion',
                   side_effect=Exception("LLM timeout")):
            result = llm_restock.get_itemprop_availability_override(
                content='<html><body>$49.99 In Stock</body></html>',
                fetcher_name='html_requests',
                fetcher_instance=None,
                url='https://example.com',
                llm_intent=None,
            )
        assert result is None


class TestLLMRestockPluginHTMLStripping:
    def test_strip_html_removes_tags(self):
        from changedetectionio.processors.restock_diff.plugins.llm_restock import _strip_html
        result = _strip_html('<html><body><p>Price: $10</p></body></html>')
        assert '<' not in result
        assert 'Price: $10' in result

    def test_strip_html_removes_scripts(self):
        from changedetectionio.processors.restock_diff.plugins.llm_restock import _strip_html
        html = '<html><head><script>var x = 1;</script></head><body>In Stock</body></html>'
        result = _strip_html(html)
        assert 'var x' not in result
        assert 'In Stock' in result

    def test_strip_html_decodes_entities(self):
        from changedetectionio.processors.restock_diff.plugins.llm_restock import _strip_html
        result = _strip_html('Price: 49&nbsp;&amp;&nbsp;in stock')
        assert '&amp;' not in result
        assert '&nbsp;' not in result
        assert 'in stock' in result

    def test_strip_html_truncates_long_content(self):
        from changedetectionio.processors.restock_diff.plugins.llm_restock import _strip_html, _MAX_CONTENT_CHARS
        long_html = '<p>' + 'x' * (_MAX_CONTENT_CHARS * 2) + '</p>'
        result = _strip_html(long_html)
        assert len(result) <= _MAX_CONTENT_CHARS


class TestLLMRestockReusableHelpers:
    """The pieces another LLM backend (a plugin not using litellm) reuses."""

    def test_build_restock_messages(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        messages = llm_restock.build_restock_messages(
            '<html><body><h1>Widget</h1>$19.99 Add to cart</body></html>',
            'https://example.com/widget', llm_intent='tell me when it is cheaper')
        assert [m['role'] for m in messages] == ['system', 'user']
        assert messages[0]['content'] == llm_restock.SYSTEM_PROMPT
        assert 'URL: https://example.com/widget' in messages[1]['content']
        assert '$19.99' in messages[1]['content']
        assert 'User notification intent: tell me when it is cheaper' in messages[1]['content']

    def test_build_restock_messages_nothing_to_send(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        assert llm_restock.build_restock_messages('', 'https://example.com') is None
        assert llm_restock.build_restock_messages('<html><body>  </body></html>', 'https://example.com') is None

    def test_cache_key_follows_model_and_prompt(self):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        a = llm_restock.build_restock_messages('<p>$1</p>', 'https://example.com/a')
        b = llm_restock.build_restock_messages('<p>$2</p>', 'https://example.com/a')
        assert llm_restock.restock_cache_key('m1', a) == llm_restock.restock_cache_key('m1', a)
        assert llm_restock.restock_cache_key('m1', a) != llm_restock.restock_cache_key('m2', a)
        assert llm_restock.restock_cache_key('m1', a) != llm_restock.restock_cache_key('m1', b)

    @pytest.mark.parametrize('raw, expected', [
        ('{"price": 19.99, "currency": "USD", "availability": "instock"}',
         {'price': 19.99, 'currency': 'USD', 'availability': 'instock'}),
        ('```json\n{"price": "1.299,95 €", "currency": "EUR", "availability": null}\n```',
         {'price': 1299.95, 'currency': 'EUR', 'availability': None}),
        ('{"price": null, "currency": null, "availability": "outofstock"}',
         {'price': None, 'currency': None, 'availability': 'outofstock'}),
        ('{"price": null, "currency": null, "availability": null}', None),
        ('Sure! The price is $19.99', None),
        ('[19.99]', None),
        ('', None),
    ])
    def test_parse_restock_reply(self, raw, expected):
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        assert llm_restock.parse_restock_reply(raw, 'https://example.com') == expected

    def test_accumulate_global_tokens_uses_given_cost(self):
        from changedetectionio.llm import evaluator
        ds = _make_datastore()
        with patch.object(evaluator, '_estimate_cost_usd', side_effect=AssertionError('should not estimate')):
            evaluator.accumulate_global_tokens(ds, 100, input_tokens=90, output_tokens=10,
                                               model='some-model', cost_usd=0.25)
        llm = ds.data['settings']['application']['llm']
        assert llm['tokens_total_cumulative'] == 100
        assert llm['cost_usd_total_cumulative'] == 0.25

    def test_alternative_backend_path_does_not_import_litellm(self):
        """litellm costs ~200MB once imported and is never released, the whole point of reusing
        these helpers from another backend is to not pay that. Fresh interpreter, since other
        tests in this process may already have imported it."""
        import subprocess, sys
        code = '''
import sys
from unittest.mock import MagicMock
from changedetectionio.processors.restock_diff.plugins import llm_restock
from changedetectionio.llm.evaluator import accumulate_global_tokens
messages = llm_restock.build_restock_messages('<p>Widget $5 Add to cart</p>', 'https://example.com')
key = llm_restock.restock_cache_key('gemini/gemini-flash-lite', messages)
result = llm_restock.parse_restock_reply('{"price": 5, "currency": "USD", "availability": "instock"}')
llm_restock.restock_cache_put(key, result)
ds = MagicMock()
ds.data = {'settings': {'application': {'llm': {}}}}
accumulate_global_tokens(ds, 10, input_tokens=8, output_tokens=2, model='gemini/gemini-flash-lite', cost_usd=0.0001)
assert result['price'] == 5.0, result
print('litellm' in sys.modules)
'''
        # CI runs pytest from inside the package dir without installing it, so the child
        # wouldn't find 'changedetectionio' - point it at the directory that contains it.
        import os, changedetectionio
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(changedetectionio.__file__)))
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [repo_root, os.environ.get('PYTHONPATH')]))}
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, env=env)
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().splitlines()[-1] == 'False', "litellm was imported"


class TestRestockHookDispatch:
    """get_itemprop_availability_from_plugin(): a third-party plugin (e.g. plain `requests` to an
    LLM, no litellm) gets the HTML and the html_to_text() version, and goes before the built-in."""

    HTML = '<html><body><h1>Widget</h1><p>Price: $12.50</p><button>Add to cart</button></body></html>'

    @pytest.fixture
    def registered(self):
        from changedetectionio.pluggy_interface import plugin_manager, register_builtin_restock_plugins
        register_builtin_restock_plugins()
        added = []

        def register(plugin):
            plugin_manager.register(plugin)
            added.append(plugin)

        yield register
        for plugin in added:
            plugin_manager.unregister(plugin)

    def _dispatch(self):
        from changedetectionio.pluggy_interface import get_itemprop_availability_from_plugin
        return get_itemprop_availability_from_plugin(self.HTML, 'html_requests', None, 'https://example.com/widget')

    def test_custom_plugin_gets_html_and_text_and_wins(self, registered):
        from changedetectionio.pluggy_interface import hookimpl
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        seen = {}

        class MyPlugin:
            @hookimpl
            def get_itemprop_availability_override(self, content, url, text):
                seen.update(content=content, text=text, url=url)
                return {'price': 12.5, 'currency': 'USD', 'availability': 'instock'}

        registered(MyPlugin())
        llm_restock.datastore = _make_datastore()
        with patch('changedetectionio.llm.client.completion') as litellm_completion:
            result = self._dispatch()

        assert result == {'price': 12.5, 'currency': 'USD', 'availability': 'instock'}
        assert seen['content'] == self.HTML
        assert 'Price: $12.50' in seen['text'] and '<p>' not in seen['text']
        # The built-in LLM plugin must not have been billed as well
        litellm_completion.assert_not_called()

    def test_custom_plugin_returning_none_falls_through_to_builtin(self, registered):
        from changedetectionio.pluggy_interface import hookimpl
        from changedetectionio.processors.restock_diff.plugins import llm_restock

        class NotMine:
            @hookimpl
            def get_itemprop_availability_override(self, content):
                return None

        registered(NotMine())
        llm_restock.datastore = _make_datastore()
        with patch('changedetectionio.llm.client.completion',
                   return_value=('{"price": 12.5, "currency": "USD", "availability": "instock"}', 50, 40, 10)):
            result = self._dispatch()
        assert result['price'] == 12.5

    def test_text_not_computed_when_nobody_asks_for_it(self, registered):
        from changedetectionio.pluggy_interface import hookimpl

        class HtmlOnly:
            @hookimpl
            def get_itemprop_availability_override(self, content):
                return {'price': 1.0, 'currency': None, 'availability': None}

        registered(HtmlOnly())
        with patch('changedetectionio.html_tools.html_to_text') as html_to_text:
            assert self._dispatch()['price'] == 1.0
        html_to_text.assert_not_called()

    def test_builtin_receives_llm_intent_through_pluggy(self, registered):
        """The built-in impl used to declare llm_intent=None, and pluggy never passes an argument
        that has a default, so the user's intent silently never reached the restock prompt."""
        from changedetectionio.pluggy_interface import get_itemprop_availability_from_plugin
        from changedetectionio.processors.restock_diff.plugins import llm_restock
        llm_restock.datastore = _make_datastore()
        with patch('changedetectionio.llm.client.completion',
                   return_value=('{"price": 12.5, "currency": "USD", "availability": "instock"}', 50, 40, 10)) as completion:
            get_itemprop_availability_from_plugin(self.HTML, 'html_requests', None, 'https://example.com/widget',
                                                  llm_intent='alert below $10')
        assert 'alert below $10' in completion.call_args.kwargs['messages'][-1]['content']
