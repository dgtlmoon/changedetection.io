import json
import os
import time
import re
from flask import url_for
from loguru import logger

from .util import set_original_response, set_modified_response, set_more_modified_response, live_server_setup, wait_for_all_checks, wait_for_notification_endpoint_output
from . util import  extract_UUID_from_client
import logging
import base64

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title, valid_notification_formats
)
from ..diff import HTML_CHANGED_STYLE
from ..model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
from ..notification_service import FormattableTimestamp


# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server, measure_memory_usage, datastore_path):
    
    set_original_response(datastore_path=datastore_path)

    # Re 360 - new install should have defaults set
    res = client.get(url_for("settings.settings_page"))
    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')+"?status_code=204"

    assert default_notification_body.encode() in res.data
    assert default_notification_title.encode() in res.data

    #####################
    # Set this up for when we remove the notification from the watch, it should fallback with these details
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": notification_url,
              "application-notification_title": "fallback-title "+default_notification_title,
              "application-notification_body": "fallback-body "+default_notification_body,
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Settings updated." in res.data

    res = client.get(url_for("settings.settings_page"))
    for k,v in valid_notification_formats.items():
        if k == USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH:
            continue
        assert f'value="{k}"'.encode() in res.data # Should be by key NOT value
        assert f'value="{v}"'.encode() not in res.data # Should be by key NOT value


    # When test mode is in BASE_URL env mode, we should see this already configured
    env_base_url = os.getenv('BASE_URL', '').strip()
    if len(env_base_url):
        logging.debug(">>> BASE_URL enabled, looking for %s", env_base_url)
        res = client.get(url_for("settings.settings_page"))
        assert bytes(env_base_url.encode('utf-8')) in res.data
    else:
        logging.debug(">>> SKIPPING BASE_URL check")

    # re #242 - when you edited an existing new entry, it would not correctly show the notification settings
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Give the thread time to pick up the first version
    wait_for_all_checks(client)

    # We write the PNG to disk, but a JPEG should appear in the notification
    # Write the last screenshot png
    testimage_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='


    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    screenshot_dir = os.path.join(datastore_path, str(uuid))
    os.makedirs(screenshot_dir, exist_ok=True)
    with open(os.path.join(screenshot_dir, 'last-screenshot.png'), 'wb') as f:
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
                                                   "Diff with args: {{diff(context=3)}}"
                                                   "Diff as Patch: {{diff_patch}}\n"
                                                   "Change datetime: {{change_datetime}}\n"
                                                   "Change datetime format: Weekday {{change_datetime(format='%A')}}\n"
                                                   "Change datetime format: {{change_datetime(format='%Y-%m-%dT%H:%M:%S%z')}}\n"
                                                   ":-)",
                              "notification_screenshot": True,
                              "notification_format": 'text'}

    notification_form_data.update({
        "url": test_url,
        "tags": "my tag, my second tag",
        "title": "my title",
        "headers": "",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y"})

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data=notification_form_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data


    # Hit the edit page, be sure that we saved it
    # Re #242 - wasnt saving?
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"))
    assert bytes(notification_url.encode('utf-8')) in res.data
    assert bytes("New ChangeDetection.io Notification".encode('utf-8')) in res.data

    ## Now recheck, and it should have sent the notification
    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    # Check no errors were recorded
    res = client.get(url_for("watchlist.index"))
    assert b'notification-error' not in res.data


    # Verify what was sent as a notification, this file should exist
    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    os.unlink(os.path.join(datastore_path, "notification.txt"))

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
    assert notification_submission_object

    import time
    # Could be from a few seconds ago (when the notification was fired vs in this test checking), so check for any
    times_possible = [str(FormattableTimestamp(int(time.time()) - i)) for i in range(15)]
    assert any(t in notification_submission for t in times_possible)

    txt = f"Weekday {FormattableTimestamp(int(time.time()))(format='%A')}"
    assert txt in notification_submission




    # We keep PNG screenshots for now
    # IF THIS FAILS YOU SHOULD BE TESTING WITH ENV VAR REMOVE_REQUESTS_OLD_SCREENSHOTS=False
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
    set_more_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)
    # Verify what was sent as a notification, this file should exist
    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    assert "Ohh yeah awesome" in notification_submission


    # Prove that "content constantly being marked as Changed with no Updating causes notification" is not a thing
    # https://github.com/dgtlmoon/changedetection.io/discussions/192
    os.unlink(os.path.join(datastore_path, "notification.txt"))

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert os.path.exists(os.path.join(datastore_path, "notification.txt")) == False

    res = client.get(url_for("settings.notification_logs"))
    # be sure we see it in the output log
    assert b'New ChangeDetection.io Notification - ' + test_url.encode('utf-8') in res.data

    set_original_response(datastore_path=datastore_path)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
        "url": test_url,
        "tags": "my tag",
        "title": "my title",
        "notification_urls": '',
        "notification_title": '',
        "notification_body": '',
        "notification_format": default_notification_format,
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    # Verify what was sent as a notification, this file should exist
    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    assert "fallback-title" in notification_submission
    assert "fallback-body" in notification_submission

    # cleanup for the next
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )


def test_notification_urls_jinja2_apprise_integration(client, live_server, measure_memory_usage, datastore_path):

    #
    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#header-manipulation
    test_notification_url = "hassio://127.0.0.1/longaccesstoken?verify=no&nid={{watch_uuid}}"

    res = client.post(
        url_for("settings.settings_page"),
        data={
              "application-fetch_backend": "html_requests",
              "application-minutes_between_check": 180,
              "application-notification_body": '{ "url" : "{{ watch_url }}", "secret": 444, "somebug": "网站监测 内容更新了", "another": "{{diff|truncate(1500)}}" }',
              "application-notification_format": default_notification_format,
              "application-notification_urls": test_notification_url,
              # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#get-parameter-manipulation
              "application-notification_title": "New ChangeDetection.io Notification - {{ watch_url }}  {{diff|truncate(200)}} ",
              },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data
    assert '网站监测'.encode() in res.data
    assert b'{{diff|truncate(1500)}}' in res.data
    assert b'{{diff|truncate(200)}}' in res.data




def test_notification_custom_endpoint_and_jinja2(client, live_server, measure_memory_usage, datastore_path):
    

    # test_endpoint - that sends the contents of a file
    # test_notification_endpoint - that takes a POST and writes it to file (test-datastore/notification.txt)

    # CUSTOM JSON BODY CHECK for POST://
    set_original_response(datastore_path=datastore_path)
    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#header-manipulation
    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?status_code=204&watch_uuid={{ watch_uuid }}&xxx={{ watch_url }}&now={% now 'Europe/London', '%Y-%m-%d' %}&+custom-header=123&+second=hello+world%20%22space%22"

    res = client.post(
        url_for("settings.settings_page"),
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
    watch_uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, tag="nice one")
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    wait_for_notification_endpoint_output(datastore_path=datastore_path)


    # Check no errors were recorded, because we asked for 204 which is slightly uncommon but is still OK
    res = client.get(url_for("watchlist.index"))
    assert b'notification-error' not in res.data

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        j = json.loads(x)
        assert j['url'].startswith('http://localhost')
        assert j['secret'] == 444
        assert j['somebug'] == '网站监测 内容更新了'


    # URL check, this will always be converted to lowercase
    assert os.path.isfile(os.path.join(datastore_path, "notification-url.txt"))
    with open(os.path.join(datastore_path, "notification-url.txt"), 'r') as f:
        notification_url = f.read()
        assert 'xxx=http' in notification_url
        # apprise style headers should be stripped
        assert 'custom-header' not in notification_url
        # Check jinja2 custom arrow/jinja2-time replace worked
        assert 'now=2' in notification_url
        # Check our watch_uuid appeared
        assert f'watch_uuid={watch_uuid}' in notification_url


    with open(os.path.join(datastore_path, "notification-headers.txt"), 'r') as f:
        notification_headers = f.read()
        assert 'custom-header: 123' in notification_headers.lower()
        assert 'second: hello world "space"' in notification_headers.lower()


    # Should always be automatically detected as JSON content type even when we set it as 'Plain Text' (default)
    assert os.path.isfile(os.path.join(datastore_path, "notification-content-type.txt"))
    with open(os.path.join(datastore_path, "notification-content-type.txt"), 'r') as f:
        assert 'application/json' in f.read()

    os.unlink(os.path.join(datastore_path, "notification-url.txt"))

    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )


#2510
#@todo run it again as text, html, htmlcolor
def test_global_send_test_notification(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt")) \

    # 1995 UTF-8 content should be encoded
    test_body = 'change detection is cool 网站监测 内容更新了 - {{diff_full}}'

    # otherwise other settings would have already existed from previous tests in this file
    res = client.post(
        url_for("settings.settings_page"),
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
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?xxx={{ watch_url }}&+custom-header=123"

    ######### Test global/system settings
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test")+"?mode=global-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        assert 'change detection is cool 网站监测 内容更新了' in x
        if 'html' in default_notification_format:
            # this should come from default text when in global/system mode here changedetectionio/notification_service.py
            assert 'title="Changed into">Example text:' in x
        else:
            assert 'title="Changed into">Example text:' not in x
            assert 'span' not in x
            assert 'Example text:' in x

    os.unlink(os.path.join(datastore_path, "notification.txt"))

    ######### Test group/tag settings
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test")+"?mode=group-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    # Give apprise time to fire
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        # Should come from notification.py default handler when there is no notification body to pull from
        assert 'change detection is cool 网站监测 内容更新了' in x

    ## Check that 'test' catches errors
    test_notification_url = 'post://akjsdfkjasdkfjasdkfjasdkjfas232323/should-error'

    ######### Test global/system settings
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test")+"?mode=global-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )
    assert res.status_code == 400
    assert (
        b"No address found" in res.data or
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data
    )
    
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )

    ######### Test global/system settings - When everything is deleted it should give a helpful error
    # See #2727
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test")+"?mode=global-settings",
        data={"notification_urls": test_notification_url},
        follow_redirects=True
    )
    assert res.status_code == 400
    assert b"Error: You must have atleast one watch configured for 'test notification' to work" in res.data


#2510
def test_single_send_test_notification_on_watch(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt")) \


    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?xxx={{ watch_url }}&+custom-header=123"
    # 1995 UTF-8 content should be encoded
    test_body = 'change detection is cool 网站监测 内容更新了 - {{diff_full}}\n\nCurrent snapshot: {{current_snapshot}}'
    ######### Test global/system settings
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test")+f"/{uuid}",
        data={"notification_urls": test_notification_url,
              "notification_body": test_body,
              "notification_format": default_notification_format,
              "notification_title": "New ChangeDetection.io Notification - {{ watch_url }}",
              },
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        assert 'change detection is cool 网站监测 内容更新了' in x
        if 'html' in default_notification_format:
            # this should come from default text when in global/system mode here changedetectionio/notification_service.py
            assert 'title="Changed into">Example text:' in x
        else:
            assert 'title="Changed into">Example text:' not in x
            assert 'span' not in x
            assert 'Example text:' in x
        #3720 current_snapshot check, was working but lets test it exactly.
        assert 'Current snapshot: Example text: example test' in x
    os.unlink(os.path.join(datastore_path, "notification.txt"))

# Regression test for #4119 - sending a test notification with 'System default' format caused a crash
def test_send_test_notification_with_system_default_format(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://') + "?status_code=204"

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # New watches default to USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH.
    # The JS sends this value verbatim from the select; it must not crash.
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test") + f"/{uuid}",
        data={
            "notification_urls": test_notification_url,
            "notification_body": default_notification_body,
            "notification_title": default_notification_title,
            "notification_format": USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH,
        },
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)


def _test_color_notifications(client, notification_body_token, datastore_path):

    set_original_response(datastore_path=datastore_path)

    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))


    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')+"?xxx={{ watch_url }}&+custom-header=123"


    # otherwise other settings would have already existed from previous tests in this file
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": notification_body_token,
            "application-notification_format": "htmlcolor",
            "application-notification_urls": test_notification_url,
            "application-notification_title": "New ChangeDetection.io Notification - {{ watch_url }}",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    set_modified_response(datastore_path=datastore_path)


    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        s = f'<span style="{HTML_CHANGED_STYLE}" role="note" aria-label="Changed text" title="Changed text">Which is across multiple lines</span><br>'
        assert s in x

    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )

# Just checks the format of the colour notifications was correct
def test_html_color_notifications(client, live_server, measure_memory_usage, datastore_path):
    _test_color_notifications(client, '{{diff}}',datastore_path=datastore_path)
    _test_color_notifications(client, '{{diff_full}}',datastore_path=datastore_path)


def _test_custom_html_in_notification_body_not_escaped(client, datastore_path, content_type=None):
    """
    #4121 - The operator's own HTML in the notification body template (e.g.
    <a href="{{watch_url}}">) must survive unescaped regardless of the watched page's
    Content-Type. The escape pass in handler.py only touches the variable *values*
    (diff/snapshot content from the page — see GHSA-q8xq-qg4x-wphg) — it leaves the
    surrounding template HTML alone.
    """
    set_original_response(datastore_path=datastore_path)

    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')

    kwargs = {'content_type': content_type} if content_type else {}
    test_url = url_for('test_endpoint', _external=True, **kwargs)

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": '<a href="{{watch_url}}">Watch Link</a> had changes\n\n{{diff}}',
            "application-notification_format": "htmlcolor",
            "application-notification_urls": test_notification_url,
            "application-notification_title": "Change detected",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)

    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()

    assert '&lt;a href=' not in x, f"Custom HTML <a> tag was incorrectly escaped (content_type={content_type})"
    assert '<a href=' in x, f"Custom HTML <a> tag not found unescaped (content_type={content_type})"
    assert '<span' in x, f"Expected color <span> tags not found (content_type={content_type})"

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)


def test_plaintext_watch_custom_html_in_notification_body_not_escaped(client, live_server, measure_memory_usage, datastore_path):
    # Diff/snapshot values are escaped for HTML notifications (covered by
    # test_html_watch_diff_content_escaped_in_html_notification). What this test
    # locks in is that the *surrounding* template HTML is left alone in every case.
    _test_custom_html_in_notification_body_not_escaped(client, datastore_path, content_type="text/plain")
    _test_custom_html_in_notification_body_not_escaped(client, datastore_path, content_type="text/html")
    _test_custom_html_in_notification_body_not_escaped(client, datastore_path, content_type=None)


def test_html_watch_diff_content_escaped_in_html_notification(client, live_server, measure_memory_usage, datastore_path):
    """
    GHSA-q8xq-qg4x-wphg — diff/snapshot content from the watched page must be
    HTML-escaped before it is rendered into an HTML-format notification, regardless
    of the watched page's Content-Type.

    Inscriptis (used to convert text/html pages to snapshot text) decodes HTML
    entities — so a page that visibly displays "&lt;a href=...&gt;" produces snapshot
    text containing literal "<a href=...>". The previous gate at handler.py:391
    only escaped when watch_mime_type matched 'text/' and not 'html', which let
    that decoded markup through to HTML emails / Telegram (parse_mode=html) /
    Discord embeds, where it renders as a real clickable link — i.e. an attacker
    who controls a watched page can inject phishing links into the operator's
    trusted notification channel.
    """
    from .util import write_test_file_and_sync

    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    # Baseline: an innocuous text/html page.
    baseline_html = "<html><body><p>nothing to see here</p></body></html>"
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), baseline_html)

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')
    # Pass content_type=text/html so the watch records 'text/html' as its content-type
    # — this is the branch the previous gate skipped escaping for.
    test_url = url_for('test_endpoint', _external=True, content_type='text/html')

    # HTML-format notification body that embeds the snapshot directly. Operators do this
    # when they want the full changed content in the alert (e.g. an email digest).
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": 'Watch had changes:\n{{current_snapshot}}',
            "application-notification_format": "html",
            "application-notification_urls": test_notification_url,
            "application-notification_title": "Change detected",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    # Now flip the page to something whose *visible* text contains entity-encoded
    # angle brackets — exactly the pattern a forum / pastebin / code-sample site uses
    # to display literal HTML on the page. Inscriptis will decode &lt;/&gt; back to
    # literal < / > in the stored snapshot.
    attacker_html = (
        '<html><body><pre>'
        '&lt;a href="https://attacker.example/payment"&gt;ACTION REQUIRED&lt;/a&gt;'
        '&lt;img src="https://attacker.example/track" width="1" height="1"&gt;'
        '</pre></body></html>'
    )
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), attacker_html)

    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        body = f.read()

    # Sanity: the snapshot really did contain the decoded markup (otherwise the test
    # would pass for the wrong reason). The escaped form must appear somewhere.
    assert '&lt;a href=' in body or '&amp;lt;a href=' in body, \
        f"Expected escaped attacker markup in notification body, got: {body!r}"

    # The bug: a live <a href="https://attacker..."> ends up in the HTML notification.
    assert '<a href="https://attacker.example/payment"' not in body, \
        f"Diff content from text/html page was NOT escaped — phishing link reached HTML notification: {body!r}"
    assert '<img src="https://attacker.example/track"' not in body, \
        f"Diff content from text/html page was NOT escaped — tracking pixel reached HTML notification: {body!r}"

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)


def test_source_url_diff_content_escaped_in_html_notification(client, live_server, measure_memory_usage, datastore_path):
    """
    GHSA-q8xq-qg4x-wphg — companion to the inscriptis test. `source:`-prefixed
    URLs short-circuit the HTML→text step (processor.py:509-511) and store the
    raw HTML body verbatim as the snapshot. That gives an attacker who controls
    a watched page a *direct* injection path — no entity-encoding tricks needed,
    any live `<a>` / `<img>` / `<script>` on the page lands straight into
    current_snapshot / raw_diff. The escape pass must catch this too.
    """
    from .util import write_test_file_and_sync

    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    # Baseline: innocuous raw HTML.
    baseline_html = "<html><body><p>nothing to see here</p></body></html>"
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), baseline_html)

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://')
    # `source:` prefix → raw HTML body is stored as-is in the snapshot (no inscriptis).
    test_url = 'source:' + url_for('test_endpoint', _external=True, content_type='text/html')

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "application-notification_body": 'Watch had changes:\n{{current_snapshot}}',
            "application-notification_format": "html",
            "application-notification_urls": test_notification_url,
            "application-notification_title": "Change detected",
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    # Modified page contains LIVE HTML directly — no entity encoding. With source:
    # this lands in the snapshot verbatim.
    attacker_html = (
        '<html><body>'
        '<a href="https://attacker.example/payment">ACTION REQUIRED</a>'
        '<img src="https://attacker.example/track" width="1" height="1">'
        '</body></html>'
    )
    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), attacker_html)

    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data

    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        body = f.read()

    # Sanity: snapshot really did carry the markup through. Escaped form must show up.
    assert '&lt;a href=' in body or '&amp;lt;a href=' in body, \
        f"Expected escaped attacker markup in notification body, got: {body!r}"

    assert '<a href="https://attacker.example/payment"' not in body, \
        f"source: URL raw HTML was NOT escaped — phishing link reached HTML notification: {body!r}"
    assert '<img src="https://attacker.example/track"' not in body, \
        f"source: URL raw HTML was NOT escaped — tracking pixel reached HTML notification: {body!r}"

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
