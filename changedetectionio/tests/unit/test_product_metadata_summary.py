#!/usr/bin/env python3
# coding=utf-8

"""Unit tests for the memory-safe, verbatim structured-metadata block used by the LLM enricher.

Run: python -m unittest changedetectionio.tests.unit.test_product_metadata_summary
"""

import json
import unittest

from changedetectionio.processors.restock_diff.pure_python_extractor import (
    extract_metadata_for_llm,
)


def _page(*scripts, head_extra=''):
    body = '\n'.join(scripts)
    return f'<html><head>{head_extra}</head><body>{body}</body></html>'


class TestExtractMetadataForLLM(unittest.TestCase):

    def test_jsonld_passed_through_verbatim(self):
        html = _page('''
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Acme Widget",
         "sku":"12345","color":"blue","releaseDate":"2026-01-02",
         "offers":{"@type":"Offer","price":"249.00","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
        </script>''')
        out = extract_metadata_for_llm(html)
        # Verbatim: fields we never "whitelisted" must still be present
        self.assertIn('JSON-LD', out)
        self.assertIn('"name":"Acme Widget"', out)
        self.assertIn('"sku":"12345"', out)
        self.assertIn('"color":"blue"', out)
        self.assertIn('"releaseDate":"2026-01-02"', out)
        self.assertIn('"availability":"https://schema.org/InStock"', out)

    def test_no_size_or_count_limit_is_imposed(self):
        # 50 products → all 50 must appear; sizing is the caller's budget, not ours.
        prods = [f'{{"@type":"Product","name":"P{i}","sku":"S{i}"}}' for i in range(50)]
        html = _page(f'<script type="application/ld+json">[{",".join(prods)}]</script>')
        out = extract_metadata_for_llm(html)
        self.assertIn('"name":"P0"', out)
        self.assertIn('"name":"P49"', out)
        self.assertNotIn('more products', out)  # no truncation marker

    def test_non_product_types_included(self):
        # News / events / etc. are passed through too — not product-only.
        html = _page('''<script type="application/ld+json">
        {"@type":"NewsArticle","headline":"Big news","datePublished":"2026-05-30"}
        </script>''')
        out = extract_metadata_for_llm(html)
        self.assertIn('"@type":"NewsArticle"', out)
        self.assertIn('"headline":"Big news"', out)

    def test_compact_reserialisation_is_valid_json(self):
        html = _page('''<script type="application/ld+json">
        {  "@type" : "Product" ,  "name" :  "Spaced Out"  }
        </script>''')
        out = extract_metadata_for_llm(html)
        blob_line = out.splitlines()[-1]
        # The re-dumped line must round-trip as valid JSON
        self.assertEqual(json.loads(blob_line)['name'], 'Spaced Out')

    def test_opengraph_page_context(self):
        html = _page(
            '<script type="application/ld+json">{"@type":"ItemList"}</script>',
            head_extra='''
                <meta property="og:site_name" content="ExampleShop">
                <meta property="og:type" content="product.group">
            ''',
        )
        out = extract_metadata_for_llm(html)
        self.assertIn('Page context: site: ExampleShop', out)
        self.assertIn('og:type: product.group', out)
        self.assertIn('"@type":"ItemList"', out)

    def test_dangling_unclosed_jsonld_is_safe(self):
        # An unterminated ld+json block must NOT swallow the document nor crash.
        html = (
            '<html><body>'
            '<script type="application/ld+json">{"@type":"Product","name":"Broken","sku":"X"'
            '<div>rest of page</div>'
            '</body></html>'
        )
        self.assertEqual(extract_metadata_for_llm(html), '')

    def test_invalid_json_skipped(self):
        html = _page('<script type="application/ld+json">{not valid json,,}</script>')
        self.assertEqual(extract_metadata_for_llm(html), '')

    def test_no_metadata_returns_empty(self):
        self.assertEqual(extract_metadata_for_llm('<html><body><p>hi</p></body></html>'), '')
        self.assertEqual(extract_metadata_for_llm(''), '')


if __name__ == '__main__':
    unittest.main()
