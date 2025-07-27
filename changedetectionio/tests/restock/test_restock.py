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


# @todo: custom strings with non ascii characters fail
def test_restock_custom_strings(client, live_server):
    """Test custom out-of-stock strings feature"""
    
    # Set up a response with custom out-of-stock text
    # Add enough content to push the target div below the 300px threshold
    test_return_data = """<html>
       <body>
       <div style="height: 400px; padding: 50px;">
       <h1>Product Page Header</h1>
       <p>Some navigation and header content that should be ignored</p>
       <p>More header content to push the real content down</p>
       <p>Even more content to ensure we're below 300px</p>
       </div>
       <div style="padding: 20px;">
       Some initial text<br>
       <p>Which is across multiple lines</p>
       <br>
       So let's see what happens.  <br>
       <div>price: $10.99</div>
       <div id="custom">Pronto en stock!</div>
       </div>
       </body>
       </html>
    """
    
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    
    test_url = url_for('test_endpoint', _external=True).replace('http://localhost', 'http://changedet')

    # Add watch with custom out-of-stock strings
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    
    # Get the UUID so we can configure the watch
    uuid = extract_UUID_from_client(client)
    
    # Configure custom out-of-stock strings
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            "url": test_url,
            'processor': 'restock_diff',
            'restock_settings-custom_outofstock_strings': 'Pronto en stock!\nCustom unavailable message',
            "tags": "",
            "headers": "",
            'fetch_backend': "html_webdriver"
        },
        follow_redirects=True
    )

    # Check that it detects as out of stock
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' in res.data, "Should detect custom out-of-stock string"
    
    # Test custom in-stock strings by changing the content
    test_return_data_instock = """<html>
       <body>
       Some initial text<br>
       <p>Which is across multiple lines</p>
       <br>
       So let's see what happens.  <br>
       <div>price: $10.99</div>
       <div id="custom">Disponible ahora</div>
       </body>
       </html>
    """
    
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data_instock)
    
    # Update the watch to include custom in-stock strings
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            "url": test_url,
            'processor': 'restock_diff',
            'restock_settings-custom_outofstock_strings': 'Pronto en stock!\nCustom unavailable message',
            'restock_settings-custom_instock_strings': 'Disponible ahora\nIn voorraad',
            "tags": "",
            "headers": "",
            'fetch_backend': "html_webdriver"
        },
        follow_redirects=True
    )
    # assert b"Updated watch." in res.data
    
    # Check again - should be detected as in stock now
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' not in res.data, "Should detect custom in-stock string and show as available"


def test_restock_custom_strings_normalization(client, live_server):
    """Test key normalization scenarios: accents, case, and spaces"""
    
    # Test page with Spanish text with accents and mixed case
    test_return_data = """<html>
       <body>
       <div>price: $10.99</div>
       <div id="status">¡TEMPORALMENTE    AGOTADO!</div>
       </body>
       </html>
    """
    
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    
    test_url = url_for('test_endpoint', _external=True).replace('http://localhost', 'http://changedet')
    
    # Add watch
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff'},
        follow_redirects=True
    )
    
    uuid = extract_UUID_from_client(client)
    
    # Configure custom string without accents, lowercase, no extra spaces
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            "url": test_url,
            'processor': 'restock_diff',
            'restock_settings-custom_outofstock_strings': 'temporalmente agotado'
        },
        follow_redirects=True
    )
    
    # Should detect as out of stock despite text differences
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'not-in-stock' in res.data, "Should match despite accents, case, and spacing differences"

