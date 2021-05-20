
import time
from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup

# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server):

    live_server_setup(live_server)
    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(3)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
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

    # Hit the edit page, be sure that we saved it
    res = client.get(
        url_for("edit_page", uuid="first"))
    assert bytes(notification_url.encode('utf-8')) in res.data

    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Did the front end see it?
    res = client.get(
        url_for("index"))

    assert bytes("just now".encode('utf-8')) in res.data


    # Check it triggered
    res = client.get(
        url_for("test_notification_counter"),
    )

    assert bytes("we hit it".encode('utf-8')) in res.data

    # Did we see the URL that had a change, in the notification?
    assert bytes("test-endpoint".encode('utf-8')) in res.data

    # Re #65 - did we see our foobar.com BASE_URL ?
    assert bytes("https://foobar.com".encode('utf-8')) in res.data
