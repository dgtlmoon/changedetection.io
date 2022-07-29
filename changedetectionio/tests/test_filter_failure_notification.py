import os
import time
import re
from flask import url_for
from .util import set_original_response, live_server_setup
from changedetectionio.model import App


def set_response_with_filter():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     <div id="nope-doesnt-exist">Some text thats the same</div>     
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def run_filter_test(client, content_filter):

    # Give the endpoint time to spin up
    time.sleep(1)
    # cleanup for the next
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )
    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt")

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tag": ''},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    # Give the thread time to pick up the first version
    time.sleep(3)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    url = url_for('test_notification_endpoint', _external=True)
    notification_url = url.replace('http', 'json')

    print(">>>> Notification URL: " + notification_url)

    # Just a regular notification setting, this will be used by the special 'filter not found' notification
    notification_form_data = {"notification_urls": notification_url,
                              "notification_title": "New ChangeDetection.io Notification - {watch_url}",
                              "notification_body": "BASE URL: {base_url}\n"
                                                   "Watch URL: {watch_url}\n"
                                                   "Watch UUID: {watch_uuid}\n"
                                                   "Watch title: {watch_title}\n"
                                                   "Watch tag: {watch_tag}\n"
                                                   "Preview: {preview_url}\n"
                                                   "Diff URL: {diff_url}\n"
                                                   "Snapshot: {current_snapshot}\n"
                                                   "Diff: {diff}\n"
                                                   "Diff Full: {diff_full}\n"
                                                   ":-)",
                              "notification_format": "Text"}

    notification_form_data.update({
        "url": test_url,
        "tag": "my tag",
        "title": "my title",
        "headers": "",
        "filter_failure_notification_send": 'y',
        "css_filter": content_filter,
        "fetch_backend": "html_requests"})

    res = client.post(
        url_for("edit_page", uuid="first"),
        data=notification_form_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(3)

    # Now the notification should not exist, because we didnt reach the threshold
    assert not os.path.isfile("test-datastore/notification.txt")

    for i in range(0, App._FILTER_FAILURE_THRESHOLD_ATTEMPTS_DEFAULT):
        res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
        time.sleep(3)

    # We should see something in the frontend
    assert b'Warning, filter' in res.data

    # Now it should exist and contain our "filter not found" alert
    assert os.path.isfile("test-datastore/notification.txt")
    notification = False
    with open("test-datastore/notification.txt", 'r') as f:
        notification = f.read()
    assert 'CSS/xPath filter was not present in the page' in notification
    assert content_filter.replace('"', '\\"') in notification

    # Remove it and prove that it doesnt trigger when not expected
    os.unlink("test-datastore/notification.txt")
    set_response_with_filter()

    for i in range(0, App._FILTER_FAILURE_THRESHOLD_ATTEMPTS_DEFAULT):
        client.get(url_for("form_watch_checknow"), follow_redirects=True)
        time.sleep(3)

    # It should have sent a notification, but..
    assert os.path.isfile("test-datastore/notification.txt")
    # but it should not contain the info about the failed filter
    with open("test-datastore/notification.txt", 'r') as f:
        notification = f.read()
    assert not 'CSS/xPath filter was not present in the page' in notification

    # cleanup for the next
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )
    os.unlink("test-datastore/notification.txt")


def test_setup(live_server):
    live_server_setup(live_server)

def test_check_css_filter_failure_notification(client, live_server):
    set_original_response()
    time.sleep(1)
    run_filter_test(client, '#nope-doesnt-exist')

def test_check_xpath_filter_failure_notification(client, live_server):
    set_original_response()
    time.sleep(1)
    run_filter_test(client, '//*[@id="nope-doesnt-exist"]')

# Test that notification is never sent