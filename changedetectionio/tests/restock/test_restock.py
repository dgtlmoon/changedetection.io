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


def set_original_response():
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

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None



def set_back_in_stock_response():
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

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

# Add a site in paused mode, add an invalid filter, we should still have visual selector data ready
def test_restock_detection(client, live_server, measure_memory_usage):

    set_original_response()
    #assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"
   #  live_server_setup(live_server) # Setup on conftest per function
    #####################
    notification_url = url_for('test_notification_endpoint', _external=True).replace('http://localhost', 'http://changedet').replace('http', 'json')


    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title "+default_notification_title,
              "application-notification_body": "fallback-body "+default_notification_body,
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_webdriver"},
        follow_redirects=True
    )
    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = url_for('test_endpoint', _external=True).replace('http://localhost', 'http://changedet')


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
    set_back_in_stock_response()
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' not in res.data

    # We should have a notification
    wait_for_notification_endpoint_output()
    assert os.path.isfile("test-datastore/notification.txt"), "Notification received"
    os.unlink("test-datastore/notification.txt")

    # Default behaviour is to only fire notification when it goes OUT OF STOCK -> IN STOCK
    # So here there should be no file, because we go IN STOCK -> OUT OF STOCK
    set_original_response()
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    time.sleep(5)
    assert not os.path.isfile("test-datastore/notification.txt"), "No notification should have fired when it went OUT OF STOCK by default"

    # BUT we should see that it correctly shows "not in stock"
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' in res.data, "Correctly showing NOT IN STOCK in the list after it changed from IN STOCK"

