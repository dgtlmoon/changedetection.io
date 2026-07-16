#!/usr/bin/env python3
import os
import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client, wait_for_notification_endpoint_output
from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)


def get_browser_fetcher_backend():
    """Examine the app's available fetchers and return the name of a browser-capable
    one (supports screenshots + visual-selector xpath data) if one is actually usable
    here, otherwise None.

    "Usable" means both: a fetcher class advertising browser capabilities is registered,
    AND a browser driver is configured in the environment to connect to. Without a driver
    the class still reports the capability but can't actually fetch.
    """
    if not (os.getenv('PLAYWRIGHT_DRIVER_URL') or os.getenv('WEBDRIVER_URL')):
        return None

    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities

    for name, _description in content_fetchers.available_fetchers():
        caps = FetcherCapabilities.from_fetcher(getattr(content_fetchers, name, None))
        if caps.supports_screenshots and caps.supports_xpath_element_data:
            return name

    return None


def set_original_response(datastore_path):
    test_return_data = """<html>
       <body>
       <section id=header style="padding: 50px; height: 350px">This is the header which should be ignored always - <span>add to cart</span></section>
       <!-- stock-not-in-stock.js will ignore text in the first 300px, see elementIsInEyeBallRange(), sometimes "add to cart" and other junk is here -->
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div>price: $10.99</div>
     <div id="sametext">Out of stock</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None



def set_back_in_stock_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div>price: $10.99</div>
     <div id="sametext">Available!</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None

def set_price_response(datastore_path, price, nonce=''):
    # JSON-LD product offer so the price + availability are extracted deterministically
    # without needing a real browser (extruct parses the raw HTML).
    # `nonce` injects throwaway body content so the page checksum differs (the check actually
    # runs instead of short-circuiting) while the price stays the same.
    test_return_data = """<html>
       <head>
       <script type="application/ld+json">
       {"@context": "https://schema.org/", "@type": "Product", "name": "Test Product",
        "offers": {"@type": "Offer", "priceCurrency": "USD", "price": "%s",
                   "availability": "https://schema.org/InStock"}}
       </script>
       </head>
       <body>
       <div id="sametext">Available!</div>
       <!-- %s -->
       </body>
     </html>
    """ % (price, nonce)

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def test_restock_price_change_direction(client, live_server, measure_memory_usage, datastore_path):
    """The watch list shows a green ▼/-% on a price drop and a red ▲/+% on a price rise.
    The arrow is computed from last_price (the previous check's price), so it reflects the
    change since the previous check and disappears once the price is stable."""

    def get_restock(client):
        datastore = client.application.config.get('DATASTORE')
        uuid = next(iter(datastore.data['watching']))
        return datastore.data['watching'][uuid]['restock']

    set_price_response(datastore_path=datastore_path, price="100.00")

    # JSON-LD restock data is parsed by extruct over the in-process html_requests fetcher,
    # so we can hit the live server on localhost directly (no Docker browser container needed).
    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff', 'fetch_backend': 'html_requests'},
        follow_redirects=True
    )
    wait_for_all_checks(client)

    # First check: there is no previous price yet, so no up/down indicator should render
    res = client.get(url_for("watchlist.index"))
    assert b'processor-restock_diff' in res.data
    assert b'price-change' not in res.data, "No price arrow should show on the very first check"
    assert get_restock(client).get('last_price') is None, "last_price should be unset on the first check"

    # Price drops 100.00 -> 82.00 => -18%, expect a green down arrow
    set_price_response(datastore_path=datastore_path, price="82.00")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'price-change down' in res.data, "Price drop should show a down arrow"
    assert '▼'.encode('utf-8') in res.data
    assert b'-18%' in res.data, "Price drop percentage should be shown"
    assert float(get_restock(client).get('last_price')) == 100.0, "last_price should be the previous check's price"

    # A price drop makes this watch a "deal": the Deals filter appears in the toolbar
    # and filtering by it (?deals=1) lists the watch.
    assert b'post-list-deals' in res.data, "Deals filter should appear when a price drop is detected"
    res_deals = client.get(url_for("watchlist.index", deals=1))
    assert b'processor-restock_diff' in res_deals.data, "?deals=1 should list the dropped-price watch"

    # Price rises 82.00 -> 90.00 => +9.8%, expect an up arrow
    set_price_response(datastore_path=datastore_path, price="90.00")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'price-change up' in res.data, "Price rise should show an up arrow"
    assert '▲'.encode('utf-8') in res.data
    assert b'+9.8%' in res.data, "Price rise percentage should be shown"
    assert float(get_restock(client).get('last_price')) == 82.0, "last_price should be the previous check's price"

    # A price rise is not a deal: the Deals filter disappears and matches nothing.
    assert b'post-list-deals' not in res.data, "Deals filter should disappear once there are no price drops"
    res_deals = client.get(url_for("watchlist.index", deals=1))
    assert b'processor-restock_diff' not in res_deals.data, "?deals=1 should match nothing after a price rise"

    # Re-check with NO price change - the page content is identical so the check short-circuits
    # (checksumFromPreviousCheckWasTheSame) and the processor never runs, so last_price is NOT
    # advanced and the arrow persists showing the last real move.
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'price-change up' in res.data, "Arrow should persist across an unchanged (short-circuited) check"
    assert b'+9.8%' in res.data, "Percentage should persist across an unchanged check"
    assert float(get_restock(client).get('last_price')) == 82.0, "last_price stays put when the check short-circuits"

    # Regression: the page CONTENT changes (so the check actually runs, no short-circuit) but the
    # PRICE stays 90.00. last_price must NOT be clobbered to 90 - it should still hold 82 so the
    # arrow persists. (Previously last_price was re-stamped every check and collapsed to == price.)
    set_price_response(datastore_path=datastore_path, price="90.00", nonce="changed-body-same-price")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert float(get_restock(client).get('last_price')) == 82.0, "last_price must be preserved when the price is unchanged but the page content changed"
    assert b'price-change up' in res.data, "Arrow should persist when only non-price content changed"
    assert b'+9.8%' in res.data


# Add a site in paused mode, add an invalid filter, we should still have visual selector data ready
def test_restock_detection(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)

    #####################
    notification_url = url_for('test_notification_endpoint', _external=True).replace('http://localhost', 'http://changedet').replace('http', 'json')

    # Prefer a browser fetcher (supports screenshots + visual selector) when one is
    # actually configured/usable here, otherwise fall back to the plain HTTP fetcher so
    # the restock logic is still exercised without needing a browser driver.
    fetch_backend = get_browser_fetcher_backend() or "html_requests"

    res = client.post(
        url_for("settings.settings_page"),
        data={"application-empty_pages_are_a_change": "y",
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': fetch_backend,
              },
        follow_redirects=True
    )

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.notifications.apprise"),
        data={"notification_urls": notification_url,
              "notification_title": "fallback-title "+default_notification_title,
              "notification_body": "fallback-body "+default_notification_body,
              "notification_format": default_notification_format},
        follow_redirects=True
    )
    # When using a browser fetcher the docker container (playwright/selenium) can't reach our
    # usual localhost test url, so rewrite it to the reachable host. With the in-process
    # html_requests fetcher we must keep the real localhost url.
    test_url = url_for('test_endpoint', _external=True)
    if fetch_backend != "html_requests":
        test_url = test_url.replace('http://localhost', 'http://changedet')


    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff'},
        follow_redirects=True
    )

    # Is it correctly show as NOT in stock?
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'processor-restock_diff' in res.data # Should have saved in restock mode
    assert b'not-in-stock' in res.data # should be out of stock

    # Is it correctly shown as in stock
    set_back_in_stock_response(datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' not in res.data

    # We should have a notification
    notification_file = os.path.join(datastore_path, "notification.txt")
    wait_for_notification_endpoint_output(datastore_path=datastore_path)
    assert os.path.isfile(notification_file), "Notification received"
    os.unlink(notification_file)

    # Default behaviour is to only fire notification when it goes OUT OF STOCK -> IN STOCK
    # So here there should be no file, because we go IN STOCK -> OUT OF STOCK
    set_original_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    time.sleep(5)
    assert not os.path.isfile(notification_file), "No notification should have fired when it went OUT OF STOCK by default"

    # BUT we should see that it correctly shows "not in stock"
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' in res.data, "Correctly showing NOT IN STOCK in the list after it changed from IN STOCK"

