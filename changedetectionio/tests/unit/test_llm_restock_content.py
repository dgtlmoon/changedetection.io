#!/usr/bin/env python3
"""
Unit tests for the LLM restock fallback's prompt-content building (no LLM call needed):

  * _extract_jsonld() keeps only JSON-LD blocks carrying price/stock info, dropping noise
    (breadcrumbs, site metadata) that otherwise crowds out the useful data.
  * _strip_html() sends the page's visible text IN ADDITION to that structured metadata —
    the real/visible price is often not in JSON-LD (placeholder "0").
  * the result cache evicts oldest-first and stays bounded.

Run from the tests/ directory:
    python -m unittest unit/test_llm_restock_content.py
"""
import unittest

from changedetectionio.processors.restock_diff.plugins import llm_restock as m


PRODUCT_LD = '{"@type":"Product","offers":{"price":"319.01","priceCurrency":"CZK","availability":"http://schema.org/InStock"}}'
BREADCRUMB_LD = '{"@type":"BreadcrumbList","itemListElement":[{"name":"a"},{"name":"b"}]}'

HTML = f"""
<html><head>
<script type="application/ld+json">{PRODUCT_LD}</script>
<script type="application/ld+json">{BREADCRUMB_LD}</script>
</head><body>
<nav>menu junk links</nav>
<h1>Olejovy filtr</h1>
<div class="price">319,01 Kc</div>
<button>Add to cart</button>
</body></html>
"""


class TestLLMRestockContent(unittest.TestCase):
    def test_jsonld_keeps_price_block_drops_breadcrumb(self):
        jsonld = m._extract_jsonld(HTML)
        self.assertIn('319.01', jsonld)            # product/price block kept
        self.assertIn('availability', jsonld)
        self.assertNotIn('BreadcrumbList', jsonld)  # noise dropped
        self.assertNotIn('itemListElement', jsonld)

    def test_strip_html_includes_both_metadata_and_visible_text(self):
        out = m._strip_html(HTML, max_chars=500)
        # structured metadata for context...
        self.assertIn('priceCurrency', out)
        # ...AND the visible page text (where the real price often actually lives)
        self.assertIn('319,01', out)
        self.assertIn('Add to cart', out)

    def test_strip_html_metadata_never_eats_whole_budget(self):
        # Even with a tiny budget, visible text must still get a share (metadata capped to half).
        big_meta_html = '<script type="application/ld+json">' + '{"price":"1",' + 'x' * 5000 + '}' + \
                        '</script><body><p>VISIBLE_TEXT_MARKER add to cart</p></body>'
        out = m._strip_html(big_meta_html, max_chars=400)
        self.assertLessEqual(len(out), 400)
        self.assertIn('VISIBLE_TEXT_MARKER', out)

    def test_result_cache_is_bounded_fifo(self):
        m._LLM_RESULT_CACHE.clear()
        for i in range(m._LLM_RESULT_CACHE_MAX + 25):
            m._llm_cache_put(f'key{i}', {'price': i})
        self.assertEqual(len(m._LLM_RESULT_CACHE), m._LLM_RESULT_CACHE_MAX)
        self.assertIsNone(m._llm_cache_get('key0'))                       # oldest evicted
        self.assertIsNotNone(m._llm_cache_get(f'key{m._LLM_RESULT_CACHE_MAX + 24}'))  # newest kept
        m._LLM_RESULT_CACHE.clear()


if __name__ == '__main__':
    unittest.main()
