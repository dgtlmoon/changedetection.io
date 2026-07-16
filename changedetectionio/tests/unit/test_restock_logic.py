#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_restock_logic

import unittest
import os

import changedetectionio.processors.restock_diff.processor as restock_diff

# mostly
class TestDiffBuilder(unittest.TestCase):

    def test_logic(self):
        assert restock_diff.is_between(number=10, lower=9, upper=11) == True, "Between 9 and 11"
        assert restock_diff.is_between(number=10, lower=0, upper=11) == True, "Between 9 and 11"
        assert restock_diff.is_between(number=10, lower=None, upper=11) == True, "Between None and 11"
        assert not restock_diff.is_between(number=12, lower=None, upper=11) == True, "12 is not between None and 11"

    def test_itemprop_availability_opengraph_fallback(self):
        """Availability/currency missing from JSON-LD should be filled from OpenGraph
        (Facebook commerce 'product:availability' / 'product:price:currency' meta tags)."""
        html_content = """<!DOCTYPE html>
        <html prefix="og: https://ogp.me/ns# product: https://ogp.me/ns/product#">
        <head>
        <meta property="og:type" content="product">
        <meta property="og:title" content="Some Product">
        <meta property="product:availability" content="in stock">
        <meta property="product:price:currency" content="EUR">
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@type": "Product", "name": "Some Product",
         "offers": {"@type": "Offer", "price": "155.55"}}
        </script>
        </head>
        <body><h1>Some Product</h1></body>
        </html>"""

        value = restock_diff.get_itemprop_availability(html_content)
        assert value.get('price') == 155.55, "price should be found via JSON-LD"
        assert value.get('availability') == 'in stock', "availability should be found via OpenGraph fallback"
        assert value.get('currency') == 'EUR', "currency should be found via OpenGraph fallback"

if __name__ == '__main__':
    unittest.main()
