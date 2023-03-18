#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client



def set_original_response():
    test_return_data = """<html>
       <body>
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
def test_restock_detection(client, live_server):

    set_original_response()
    #assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    time.sleep(1)
    live_server_setup(live_server)
    #####################
    res = client.post(
        url_for("settings_page"),
        data={
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_webdriver"},
        follow_redirects=True
    )
    # Add our URL to the import page, because the docker container (playwright/selenium) wont be able to connect to our usual test url
    test_url = url_for('test_endpoint', _external=True).replace('http://localhost', 'http://changedet')


    client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tag": '', 'processor': 'restock_diff'},
        follow_redirects=True
    )

    # Is it correctly show as NOT in stock?
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'not-in-stock' in res.data

    # Is it correctly shown as in stock
    set_back_in_stock_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.get(url_for("index"))
    assert b'not-in-stock' not in res.data