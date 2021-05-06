#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
import pytest

def test_setup_liveserver(live_server):


    # Just return the text file so we trigger a change.
    @live_server.app.route('/changedata', methods=['GET'])
    def changedata():
        with open("test-datastore/output.txt", "r") as f:
            return f.read()

    @live_server.app.route('/test_notification_endpoint', methods=['POST'])
    def test_notification_endpoint():
        with open("test-datastore/count.txt", "w") as f:
            f.write("we hit it")
        return "alright, you hit it"

    # And this should return not zero.
    @live_server.app.route('/test_notification_counter')
    def test_notification_counter():
        with open("test-datastore/count.txt", "r") as f:
            return f.read()


    live_server.start()

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)


def set_modified_response():
    test_return_data = """<html>
       <body>
     Some NEW nice initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     </body>
     </html>

    """

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)




def test_check_notification(client, live_server):

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('changedata', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(3)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    url = url_for('test_notification_endpoint', _external=True)
    notification_url = url.replace('http', 'json')
    print (">>>> Notification URL: "+notification_url)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"notification_urls": notification_url, "url": test_url, "tag": "", "headers": ""},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    time.sleep(3)

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)


    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Check it triggered
    res = client.get(
        url_for("test_notification_counter"),
    )
    print (res.data)

    assert bytes("we hit it".encode('utf-8')) in res.data

