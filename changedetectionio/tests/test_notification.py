import os
import time
import re
from flask import url_for
from . util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup
import logging
from changedetectionio.notification import default_notification_body, default_notification_title

def test_setup(live_server):
    live_server_setup(live_server)

# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server):

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(3)

    # Re 360 - new install should have defaults set
    res = client.get(url_for("settings_page"))
    assert default_notification_body.encode() in res.data
    assert default_notification_title.encode() in res.data

    # When test mode is in BASE_URL env mode, we should see this already configured
    env_base_url = os.getenv('BASE_URL', '').strip()
    if len(env_base_url):
        logging.debug(">>> BASE_URL enabled, looking for %s", env_base_url)
        res = client.get(url_for("settings_page"))
        assert bytes(env_base_url.encode('utf-8')) in res.data
    else:
        logging.debug(">>> SKIPPING BASE_URL check")

    # re #242 - when you edited an existing new entry, it would not correctly show the notification settings
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("api_watch_add"),
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

    print (">>>> Notification URL: "+notification_url)

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
        "fetch_backend": "html_requests"})

    res = client.post(
        url_for("edit_page", uuid="first"),
        data=notification_form_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data


    # Hit the edit page, be sure that we saved it
    # Re #242 - wasnt saving?
    res = client.get(
        url_for("edit_page", uuid="first"))
    assert bytes(notification_url.encode('utf-8')) in res.data
    assert bytes("New ChangeDetection.io Notification".encode('utf-8')) in res.data



    ## Now recheck, and it should have sent the notification
    time.sleep(3)
    set_modified_response()

    notification_submission = None

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    os.unlink("test-datastore/notification.txt")

    # Did we see the URL that had a change, in the notification?
    # Diff was correctly executed
    assert test_url in notification_submission
    assert ':-)' in notification_submission
    assert "Diff Full: Some initial text" in notification_submission
    assert "Diff: (changed) Which is across multiple lines" in notification_submission
    assert "(into   ) which has this one new line" in notification_submission
    # Re #342 - check for accidental python byte encoding of non-utf8/string
    assert "b'" not in notification_submission
    assert re.search('Watch UUID: [0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', notification_submission, re.IGNORECASE)
    assert "Watch title: my title" in notification_submission
    assert "Watch tag: my tag" in notification_submission
    assert "diff/" in notification_submission
    assert "preview/" in notification_submission
    assert ":-)" in notification_submission
    assert "New ChangeDetection.io Notification - {}".format(test_url) in notification_submission

    if env_base_url:
        # Re #65 - did we see our BASE_URl ?
        logging.debug (">>> BASE_URL checking in notification: %s", env_base_url)
        assert env_base_url in notification_submission
    else:
        logging.debug(">>> Skipping BASE_URL check")



    # This should insert the {current_snapshot}
    set_more_modified_response()
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    assert "Ohh yeah awesome" in notification_submission


    # Prove that "content constantly being marked as Changed with no Updating causes notification" is not a thing
    # https://github.com/dgtlmoon/changedetection.io/discussions/192
    os.unlink("test-datastore/notification.txt")

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(1)
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(1)
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(1)
    assert os.path.exists("test-datastore/notification.txt") == False

    # cleanup for the next
    client.get(
        url_for("api_delete", uuid="all"),
        follow_redirects=True
    )


def test_notification_validation(client, live_server):
    #live_server_setup(live_server)
    time.sleep(3)
    # re #242 - when you edited an existing new entry, it would not correctly show the notification settings
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("api_watch_add"),
        data={"url": test_url, "tag": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    # Re #360 some validation
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"notification_urls": 'json://localhost/foobar',
              "notification_title": "",
              "notification_body": "",
              "notification_format": "Text",
              "url": test_url,
              "tag": "my tag",
              "title": "my title",
              "headers": "",
              "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Notification Body and Title is required when a Notification URL is used" in res.data

    # Now adding a wrong token should give us an error
    res = client.post(
        url_for("settings_page"),
        data={"application-notification_title": "New ChangeDetection.io Notification - {watch_url}",
              "application-notification_body": "Rubbish: {rubbish}\n",
              "application-notification_format": "Text",
              "application-notification_urls": "json://localhost/foobar",
              "requests-time_between_check-minutes": 180,
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )

    assert bytes("is not a valid token".encode('utf-8')) in res.data

    # cleanup for the next
    client.get(
        url_for("api_delete", uuid="all"),
        follow_redirects=True
    )
