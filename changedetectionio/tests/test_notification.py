import os
import time
import re
from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup

# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server):

    live_server_setup(live_server)
    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(3)

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
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"notification_urls": notification_url,
              "notification_title": "New ChangeDetection.io Notification - {watch_url}",
              "notification_body": "BASE URL: {base_url}\n"
                                   "Watch URL: {watch_url}\n"
                                   "Watch UUID: {watch_uuid}\n"
                                   "Watch title: {watch_title}\n"
                                   "Watch tag: {watch_tag}\n"
                                   "Preview: {preview_url}\n"
                                   "Diff URL: {diff_url}\n"
                                   "Snapshot: {current_snapshot}\n"
                                   ":-)",
              "url": test_url,
              "tag": "my tag",
              "title": "my title",
              "headers": "",
              "fetch_backend": "html_requests",
              "trigger_check": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    assert b"Notifications queued" in res.data

    # Hit the edit page, be sure that we saved it
    res = client.get(
        url_for("edit_page", uuid="first"))
    assert bytes(notification_url.encode('utf-8')) in res.data

    # Re #242 - wasnt saving?
    assert bytes("New ChangeDetection.io Notification".encode('utf-8')) in res.data



    # Because we hit 'send test notification on save'
    time.sleep(3)

    notification_submission = None

    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
        # Did we see the URL that had a change, in the notification?

    assert test_url in notification_submission

    os.unlink("test-datastore/notification.txt")

    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Did the front end see it?
    res = client.get(
        url_for("index"))

    assert bytes("just now".encode('utf-8')) in res.data

    notification_submission=None
    # Verify what was sent as a notification
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
        # Did we see the URL that had a change, in the notification?

    assert test_url in notification_submission

        # Re #65 - did we see our foobar.com BASE_URL ?
        #assert bytes("https://foobar.com".encode('utf-8')) in notification_submission


    ##  Now configure something clever, we go into custom config (non-default) mode, this is returned by the endpoint
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(";jasdhflkjadshf kjhsdfkjl ahslkjf haslkjd hfaklsj hf\njl;asdhfkasj stuff we will detect\n")

    res = client.post(
        url_for("settings_page"),
        data={"notification_title": "New ChangeDetection.io Notification - {watch_url}",
              "notification_urls": "json://foobar.com", #Re #143 should not see that it sent without [test checkbox]
              "minutes_between_check": 180,
              "fetch_backend": "html_requests",
              },
        follow_redirects=True
    )
    assert b"Settings updated." in res.data
    # Re #143 - should not see this if we didnt hit the test box
    assert b"Notifications queued" not in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Did the front end see it?
    res = client.get(
        url_for("index"))

    assert bytes("just now".encode('utf-8')) in res.data

    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()

        assert re.search('Watch UUID: [0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', notification_submission, re.IGNORECASE)
        assert "Watch title: my title" in notification_submission
        assert "Watch tag: my tag" in notification_submission
        assert "diff/" in notification_submission
        assert "preview/" in notification_submission
        assert ":-)" in notification_submission
        assert "New ChangeDetection.io Notification - {}".format(test_url) in notification_submission
        # This should insert the {current_snapshot}
        assert "stuff we will detect" in notification_submission

    # Prove that "content constantly being marked as Changed with no Updating causes notification" is not a thing
    # https://github.com/dgtlmoon/changedetection.io/discussions/192
    os.unlink("test-datastore/notification.txt")

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    assert os.path.exists("test-datastore/notification.txt") == False


    # Now adding a wrong token should give us an error
    res = client.post(
        url_for("settings_page"),
        data={"notification_title": "New ChangeDetection.io Notification - {watch_url}",
              "notification_body": "Rubbish: {rubbish}\n",
              "notification_urls": "json://foobar.com",
              "minutes_between_check": 180,
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )

    assert bytes("is not a valid token".encode('utf-8')) in res.data