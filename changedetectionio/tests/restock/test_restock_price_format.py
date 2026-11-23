#!/usr/bin/env python3
"""Prices shown with the currency's own decimal places (ISO 4217) in the visitor's language, the same on the watch
list and the price history page (#4615). The graph does the same in static/js/restock-price-graph.js fmtPrice()."""
import os

from flask import url_for
from flask_babel import refresh

# flask_babel caches the locale on `g`, which a test shares across requests (in production each request has its
# own), so refresh() before switching language

from ..util import wait_for_all_checks, delete_all_watches


def _set_product(datastore_path, price, currency):
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(f"""<html><head><script type="application/ld+json">
        {{"@context": "https://schema.org/", "@type": "Product", "name": "Test Product",
          "offers": {{"@type": "Offer", "priceCurrency": "{currency}", "price": "{price}",
                     "availability": "https://schema.org/InStock"}}}}
        </script></head><body>Available!</body></html>""")


def test_format_price_filter(client, live_server, measure_memory_usage, datastore_path):
    format_price = client.application.jinja_env.filters['format_price']
    cases = (
        # Accept-Language, value, currency, expected
        ('ja', 12345.0, 'JPY', '￥12,345'),          # JPY has no decimal places
        ('en-US', 12345.0, 'JPY', '¥12,345'),
        ('en-US', 1234.5, 'USD', '$1,234.50'),
        ('de', 1234.5, 'EUR', '1.234,50\xa0€'),     # the visitor's separators and symbol position
        ('cs', 42000.1, 'CZK', '42\xa0000,10\xa0Kč'),  # Czech: space for thousands, comma for decimals
        ('ko', 4.2, 'AUD', 'AU$4.20'),             # Korean writes decimals like English
        ('en-US', 1234.5, 'KWD', 'KWD1,234.500'),   # three decimal places
        ('en-US', 1234.5, 'jpy', '¥1,234'),         # lower case code from the page, rounded to the currency
        ('en-US', 1234.5, '', '1,234.50'),          # no currency: two decimals
        ('de', 1234.5, '$', '1.234,50 $'),          # not an ISO 4217 code: two decimals and the page's text
    )
    for accept_language, value, currency, expected in cases:
        with client.application.test_request_context(headers={'Accept-Language': accept_language}):
            refresh()
            assert format_price(value, currency) == expected, (accept_language, value, currency)

    # No browser language: the default language, not the server's locale
    with client.application.test_request_context():
        refresh()
        assert format_price(12345.0, 'JPY') == 'JP¥12,345'


def test_price_display_matches_across_pages(client, live_server, measure_memory_usage, datastore_path):
    # Two checks, the history page needs two snapshots, and the watch list then shows the previous price too
    _set_product(datastore_path, price='13000', currency='JPY')
    client.post(url_for("ui.ui_views.form_quick_watch_add"),
                data={"url": url_for('test_endpoint', _external=True), "tags": '', 'processor': 'restock_diff',
                      'fetch_backend': 'html_requests'}, follow_redirects=True)
    wait_for_all_checks(client)
    _set_product(datastore_path, price='12345', currency='JPY')
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    uuid = next(iter(client.application.config.get('DATASTORE').data['watching']))

    for accept_language, expected, previous in (('ja', '￥12,345', '￥13,000'), ('en-US', '¥12,345', '¥13,000'),
                                                (None, 'JP¥12,345', 'JP¥13,000')):
        headers = {'Accept-Language': accept_language} if accept_language else {}
        refresh()
        watch_list = client.get(url_for('watchlist.index'), headers=headers).get_data(as_text=True)
        assert expected in watch_list, accept_language
        assert previous in watch_list, "the previous price in the price change tooltip"
        assert '12,345.00' not in watch_list and '12345.0' not in watch_list, "no decimals for JPY"

        refresh()
        history = client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid), headers=headers).get_data(as_text=True)
        assert f'<span class="restock-latest-price">{expected}</span>' in history, accept_language

    # The graph's fmtPrice() reads the page's language from <html lang>, which is never "None"
    refresh()
    page = client.get(url_for('watchlist.index')).get_data(as_text=True)
    assert '<html lang="en-GB"' in page and 'lang="None"' not in page

    delete_all_watches(client)
