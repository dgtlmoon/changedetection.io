#!/usr/bin/env python3
"""
#2707 - In restock mode a CSS/XPath filter pointing at the price sets the price, for shops
with no (or wrong, or several) structured price data.
"""
import os
from flask import url_for
from ..util import wait_for_all_checks, delete_all_watches


def _write(datastore_path, body, head=''):
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(f"<html><head>{head}</head><body>{body}</body></html>")


LD_JSON_100_USD = """<script type="application/ld+json">
{"@context": "https://schema.org/", "@type": "Product", "name": "Test Product",
 "offers": {"@type": "Offer", "priceCurrency": "USD", "price": "100.00",
            "availability": "https://schema.org/InStock"}}
</script>"""


def _add_restock_watch(client):
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": url_for('test_endpoint', _external=True), "tags": '',
              'processor': 'restock_diff', 'fetch_backend': 'html_requests'},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    datastore = client.application.config.get('DATASTORE')
    uuid = next(iter(datastore.data['watching']))
    return datastore.data['watching'][uuid]


def _recheck(client):
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)


def test_restock_price_from_include_filters(client, live_server, measure_memory_usage, datastore_path):
    # No structured data at all, the price is only in some messy text
    _write(datastore_path, '<div class="junk">Free delivery over $50</div>'
                           '<span class="price">Mondayprice$45.23 only</span>')
    watch = _add_restock_watch(client)
    assert 'Unable to extract' in (watch.get('last_error') or ''), "Without a filter there is nothing to go on"

    watch['include_filters'] = ['.price']
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 45.23
    assert watch['restock']['currency'] == '$'

    res = client.get(url_for("watchlist.index"))
    assert b'45.23' in res.data, "Price from the filter shows in the watch list restock & price column"

    # XPath works the same, and the price changing is followed
    _write(datastore_path, '<span class="price">Now only 39,99 $</span>')
    watch['include_filters'] = ['xpath://span[@class="price"]']
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 39.99
    assert watch['restock']['last_price'] == 45.23

    delete_all_watches(client)


def test_restock_include_filters_beat_structured_data(client, live_server, measure_memory_usage, datastore_path):
    # The page metadata says 100.00 USD, the user's filter points at the real price
    _write(datastore_path, '<span id="real-price">$82.00</span>', head=LD_JSON_100_USD)
    watch = _add_restock_watch(client)
    assert watch['restock']['price'] == 100.0

    watch['include_filters'] = ['#real-price']
    _recheck(client)
    assert watch['restock']['price'] == 82.0
    assert watch['restock']['currency'] == 'USD', "The page's ISO currency code is kept over the snippet's '$'"
    assert watch['restock']['in_stock'] is True, "Stock still comes from the page metadata"

    delete_all_watches(client)


def test_restock_price_from_extract_text_and_lines(client, live_server, measure_memory_usage, datastore_path):
    # The rest of 'Filters & Triggers' works too, it's text mode's own pipeline
    _write(datastore_path, '<div>Shipping $5.00</div><div>Our price today: $45.23</div><div>Members $40.00</div>')
    watch = _add_restock_watch(client)

    watch['extract_lines_containing'] = ['our price']
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 45.23

    watch['extract_lines_containing'] = []
    watch['extract_text'] = [r'/Members \$[\d.]+/']
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 40.0

    delete_all_watches(client)


def test_restock_ldjson_price_tracker_is_not_a_user_filter(client, live_server, measure_memory_usage, datastore_path):
    # Watches switched over from text mode's "track this price" prompt carry
    # track_ldjson_price_data=accepted, that must not be treated as the user picking the price
    from changedetectionio.blueprint.price_data_follower import PRICE_DATA_TRACK_ACCEPT
    _write(datastore_path, '<div>junk $1.00 and $2.00</div>', head=LD_JSON_100_USD)
    watch = _add_restock_watch(client)
    watch['track_ldjson_price_data'] = PRICE_DATA_TRACK_ACCEPT
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 100.0

    delete_all_watches(client)


def test_restock_include_filters_bad_selection(client, live_server, measure_memory_usage, datastore_path):
    _write(datastore_path, '<div class="price">was $59.99 now $45.23</div>', head=LD_JSON_100_USD)
    watch = _add_restock_watch(client)

    # Selected too much, two prices - an error, never a guess
    watch['include_filters'] = ['.price']
    _recheck(client)
    assert 'more than one price' in (watch.get('last_error') or '')

    # Removing the old price inside the selection fixes it, removal runs before the include filter
    _write(datastore_path, '<div class="price">was <del>$59.99</del> now $45.23</div>', head=LD_JSON_100_USD)
    watch['subtractive_selectors'] = ['.price del']
    _recheck(client)
    assert not watch.get('last_error'), watch.get('last_error')
    assert watch['restock']['price'] == 45.23
    watch['subtractive_selectors'] = []

    # Selected something with no price in it
    _write(datastore_path, '<div class="price">Call for pricing</div>', head=LD_JSON_100_USD)
    _recheck(client)
    assert 'no price was found' in (watch.get('last_error') or '')
    assert 'Call for pricing' in watch.get('last_error')

    # Filter that matches nothing, same as text mode
    watch['include_filters'] = ['#does-not-exist']
    _recheck(client)
    assert 'no filters were found' in (watch.get('last_error') or '')

    delete_all_watches(client)
