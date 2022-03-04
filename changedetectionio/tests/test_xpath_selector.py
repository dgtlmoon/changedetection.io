#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_modified_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  THIS CHANGES AND SHOULDNT TRIGGER A CHANGE</br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some new text</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None


def test_check_markup_xpath_filter_restriction(client, live_server):
    sleep_time_for_fetch_thread = 3

    xpath_filter = "//*[contains(@class, 'sametext')]"

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": xpath_filter, "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # view it/reset state back to viewed
    client.get(url_for("diff_history_page", uuid="first"), follow_redirects=True)

    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data


def test_xpath_validation(client, live_server):

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": "/something horrible", "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"is not a valid XPath expression" in res.data