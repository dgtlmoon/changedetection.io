"""
Tests for the LLM restock fallback plugin.

All LLM calls are mocked — no real API key required.
"""
import json
import pytest
from unittest.mock import patch, MagicMock


def _make_datastore(llm_model='gpt-4o-mini', enabled=True):
    """Minimal datastore mock with the fields the plugin reads."""
    ds = MagicMock()
    ds.data = {
        'settings': {
            'application': {
                'llm_restock_use_fallback_extract': enabled,
                'llm': {
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
                    'llm_restock_use_fallback_extract': True,
                    # No 'llm' key → get_llm_config returns None
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
        def fake_completion(model, messages, api_key, api_base, max_tokens):
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
        def fake_completion(model, messages, api_key, api_base, max_tokens):
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
