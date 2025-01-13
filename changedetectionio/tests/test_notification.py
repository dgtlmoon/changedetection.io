import json
import os
import time
import re
from flask import url_for
from loguru import logger

from .util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, wait_for_all_checks, \
    set_longer_modified_response
from . util import  extract_UUID_from_client
import logging
import base64

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)

def test_setup(live_server):
    live_server_setup(live_server)

# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    set_original_response()

    # Re 360 - new install should have defaults set
    res = client.get(url_for("settings_page"))
    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')+"?status_code=204"

    assert default_notification_body.encode() in res.data
    assert default_notification_title.encode() in res.data

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title "+default_notification_title,
              "application-notification_body": "fallback-body "+default_notification_body,
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

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
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Give the thread time to pick up the first version
    wait_for_all_checks(client)

    # We write the PNG to disk, but a JPEG should appear in the notification
    # Write the last screenshot png
    testimage_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='


    uuid = extract_UUID_from_client(client)
    datastore = 'test-datastore'
    with open(os.path.join(datastore, str(uuid), 'last-screenshot.png'), 'wb') as f:
        f.write(base64.b64decode(testimage_png))

    # Goto the edit page, add our ignore text
    # Add our URL to the import page

    print (">>>> Notification URL: "+notification_url)

    notification_form_data = {"notification_urls": notification_url,
                              "notification_title": "New ChangeDetection.io Notification - {{watch_url}}",
                              "notification_body": "BASE URL: {{base_url}}\n"
                                                   "Watch URL: {{watch_url}}\n"
                                                   "Watch UUID: {{watch_uuid}}\n"
                                                   "Watch title: {{watch_title}}\n"
                                                   "Watch tag: {{watch_tag}}\n"
                                                   "Preview: {{preview_url}}\n"
                                                   "Diff URL: {{diff_url}}\n"
                                                   "Snapshot: {{current_snapshot}}\n"
                                                   "Diff: {{diff}}\n"
                                                   "Diff Added: {{diff_added}}\n"
                                                   "Diff Removed: {{diff_removed}}\n"
                                                   "Diff Full: {{diff_full}}\n"
                                                   "Diff as Patch: {{diff_patch}}\n"
                                                   ":-)",
                              "notification_screenshot": True,
                              "notification_format": "Text"}

    notification_form_data.update({
        "url": test_url,
        "tags": "my tag, my second tag",
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
    wait_for_all_checks(client)
    set_modified_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    time.sleep(3)

    # Check no errors were recorded
    res = client.get(url_for("index"))
    assert b'notification-error' not in res.data


    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    os.unlink("test-datastore/notification.txt")

    # Did we see the URL that had a change, in the notification?
    # Diff was correctly executed

    assert "Diff Full: Some initial text" in notification_submission
    assert "Diff: (changed) Which is across multiple lines" in notification_submission
    assert "(into) which has this one new line" in notification_submission
    # Re #342 - check for accidental python byte encoding of non-utf8/string
    assert "b'" not in notification_submission
    assert re.search('Watch UUID: [0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}', notification_submission, re.IGNORECASE)
    assert "Watch title: my title" in notification_submission
    assert "Watch tag: my tag, my second tag" in notification_submission
    assert "diff/" in notification_submission
    assert "preview/" in notification_submission
    assert ":-)" in notification_submission
    assert "New ChangeDetection.io Notification - {}".format(test_url) in notification_submission
    assert test_url in notification_submission
    assert ':-)' in notification_submission
    # Check the attachment was added, and that it is a JPEG from the original PNG
    notification_submission_object = json.loads(notification_submission)
    # We keep PNG screenshots for now
    assert notification_submission_object['attachments'][0]['filename'] == 'last-screenshot.png'
    assert len(notification_submission_object['attachments'][0]['base64'])
    assert notification_submission_object['attachments'][0]['mimetype'] == 'image/png'
    jpeg_in_attachment = base64.b64decode(notification_submission_object['attachments'][0]['base64'])

    # Assert that the JPEG is readable (didn't get chewed up somewhere)
    from PIL import Image
    import io
    assert Image.open(io.BytesIO(jpeg_in_attachment))

    if env_base_url:
        # Re #65 - did we see our BASE_URl ?
        logging.debug (">>> BASE_URL checking in notification: %s", env_base_url)
        assert env_base_url in notification_submission
    else:
        logging.debug(">>> Skipping BASE_URL check")


    # This should insert the {current_snapshot}
    set_more_modified_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(3)
    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    assert "Ohh yeah awesome" in notification_submission


    # Prove that "content constantly being marked as Changed with no Updating causes notification" is not a thing
    # https://github.com/dgtlmoon/changedetection.io/discussions/192
    os.unlink("test-datastore/notification.txt")

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert os.path.exists("test-datastore/notification.txt") == False

    res = client.get(url_for("notification_logs"))
    # be sure we see it in the output log
    assert b'New ChangeDetection.io Notification - ' + test_url.encode('utf-8') in res.data

    set_original_response()
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
        "url": test_url,
        "tags": "my tag",
        "title": "my title",
        "notification_urls": '',
        "notification_title": '',
        "notification_body": '',
        "notification_format": default_notification_format,
        "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    time.sleep(2)

    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    assert "fallback-title" in notification_submission
    assert "fallback-body" in notification_submission

    # cleanup for the next
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )

def test_notification_validation(client, live_server, measure_memory_usage):

    time.sleep(1)

    # re #242 - when you edited an existing new entry, it would not correctly show the notification settings
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    # Re #360 some validation
#    res = client.post(
#        url_for("edit_page", uuid="first"),
#        data={"notification_urls": 'json://localhost/foobar',
#              "notification_title": "",
#              "notification_body": "",
#              "notification_format": "Text",
#              "url": test_url,
#              "tag": "my tag",
#              "title": "my title",
#              "headers": "",
#              "fetch_backend": "html_requests"},
#        follow_redirects=True
#    )
#    assert b"Notification Body and Title is required when a Notification URL is used" in res.data

    # cleanup for the next
    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )



def test_notification_custom_endpoint_and_jinja2(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    # test_endpoint - that sends the contents of a file
    # test_notification_endpoint - that takes a POST and writes it to file (test-datastore/notification.txt)

    # CUSTOM JSON BODY CHECK for POST://
    set_original_response()
    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#header-manipulation
    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?status_code=204&xxx={{ watch_url }}&+custom-header=123&+second=hello+world%20%22space%22"

    res = client.post(
        url_for("settings_page"),
        data={
              "application-fetch_backend": "html_requests",
              "application-minutes_between_check": 180,
              "application-notification_body": '{ "url" : "{{ watch_url }}", "secret": 444, "somebug": "网站监测 内容更新了" }',
              "application-notification_format": default_notification_format,
              "application-notification_urls": test_notification_url,
              # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
              "application-notification_title": "New ChangeDetection.io Notification - {{ watch_url }} ",
              },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    # Add a watch and trigger a HTTP POST
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    wait_for_all_checks(client)
    set_modified_response()

    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    time.sleep(2) # plus extra delay for notifications to fire


    # Check no errors were recorded, because we asked for 204 which is slightly uncommon but is still OK
    res = client.get(url_for("index"))
    assert b'notification-error' not in res.data

    with open("test-datastore/notification.txt", 'r') as f:
        x = f.read()
        j = json.loads(x)
        assert j['url'].startswith('http://localhost')
        assert j['secret'] == 444
        assert j['somebug'] == '网站监测 内容更新了'


    # URL check, this will always be converted to lowercase
    assert os.path.isfile("test-datastore/notification-url.txt")
    with open("test-datastore/notification-url.txt", 'r') as f:
        notification_url = f.read()
        assert 'xxx=http' in notification_url
        # apprise style headers should be stripped
        assert 'custom-header' not in notification_url

    with open("test-datastore/notification-headers.txt", 'r') as f:
        notification_headers = f.read()
        assert 'custom-header: 123' in notification_headers.lower()
        assert 'second: hello world "space"' in notification_headers.lower()


    # Should always be automatically detected as JSON content type even when we set it as 'Text' (default)
    assert os.path.isfile("test-datastore/notification-content-type.txt")
    with open("test-datastore/notification-content-type.txt", 'r') as f:
        assert 'application/json' in f.read()

    os.unlink("test-datastore/notification-url.txt")

    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )


#2510
def test_global_send_test_notification(client, live_server, measure_memory_usage):

    #live_server_setup(live_server)
    set_original_response()
    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt") \

    # 1995 UTF-8 content should be encoded
    test_body = 'change detection is cool 网站监测 内容更新了'

    # otherwise other settings would have already existed from previous tests in this file
    res = client.post(
        url_for("settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": test_body,
            "application-notification_format": default_notification_format,
            "application-notification_urls": "",
            "application-notification_title": "New ChangeDetection.io Notification - {{ watch_url }}",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?xxx={{ watch_url }}&+custom-header=123"

    ######### Test global/system settings
    res = client.post(
        url_for("ajax_callback_send_notification_test")+"?mode=global-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500


    with open("test-datastore/notification.txt", 'r') as f:
        x = f.read()
        assert test_body in x

    os.unlink("test-datastore/notification.txt")

    ######### Test group/tag settings
    res = client.post(
        url_for("ajax_callback_send_notification_test")+"?mode=group-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    # Give apprise time to fire
    time.sleep(4)

    with open("test-datastore/notification.txt", 'r') as f:
        x = f.read()
        # Should come from notification.py default handler when there is no notification body to pull from
        assert 'change detection is cool 网站监测 内容更新了' in x

    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )

    ######### Test global/system settings - When everything is deleted it should give a helpful error
    # See #2727
    res = client.post(
        url_for("ajax_callback_send_notification_test")+"?mode=global-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )
    assert res.status_code == 400
    assert b"Error: You must have atleast one watch configured for 'test notification' to work" in res.data


def _test_color_notifications(client, notification_body_token):

    from changedetectionio.diff import ADDED_STYLE, REMOVED_STYLE

    set_original_response()

    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt")


    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?xxx={{ watch_url }}&+custom-header=123"


    # otherwise other settings would have already existed from previous tests in this file
    res = client.post(
        url_for("settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": notification_body_token,
            "application-notification_format": "HTML Color",
            "application-notification_urls": test_notification_url,
            "application-notification_title": "New ChangeDetection.io Notification - {{ watch_url }}",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    set_modified_response()


    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    wait_for_all_checks(client)
    time.sleep(3)

    with open("test-datastore/notification.txt", 'r') as f:
        x = f.read()
        assert f'<span style="{REMOVED_STYLE}">Which is across multiple lines' in x


    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )

def test_html_color_notifications(client, live_server, measure_memory_usage):

    #live_server_setup(live_server)
    _test_color_notifications(client, '{{diff}}')
    _test_color_notifications(client, '{{diff_full}}')
    