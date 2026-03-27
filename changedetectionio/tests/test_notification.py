import json
import os
import time
import re
from flask import url_for
from loguru import logger

from .util import (set_original_response, set_modified_response, set_more_modified_response,
                   live_server_setup, wait_for_all_checks, wait_for_notification_endpoint_output,
                   add_notification_profile, set_watch_notification_profile, set_system_notification_profile,
                   clear_notification_profiles)
from .util import extract_UUID_from_client
import logging
import base64

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title, valid_notification_formats
)
from ..diff import HTML_CHANGED_STYLE
from ..notification_service import FormattableTimestamp


# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_check_notification(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json') + "?status_code=204"
    datastore = client.application.config.get('DATASTORE')

    # Settings page should load OK with no inline notification fields (they're now in profiles)
    res = client.get(url_for("settings.settings_page"))
    assert res.status_code == 200

    # Create a system-level fallback profile
    sys_profile_uuid = add_notification_profile(
        datastore,
        notification_url=notification_url,
        notification_title="fallback-title " + default_notification_title,
        notification_body="fallback-body " + default_notification_body,
        notification_format=default_notification_format,
        name="System Fallback",
    )
    set_system_notification_profile(datastore, sys_profile_uuid)

    # When test mode is in BASE_URL env mode, we should see this already configured
    env_base_url = os.getenv('BASE_URL', '').strip()
    if len(env_base_url):
        logging.debug(">>> BASE_URL enabled, looking for %s", env_base_url)
        res = client.get(url_for("settings.settings_page"))
        assert bytes(env_base_url.encode('utf-8')) in res.data
    else:
        logging.debug(">>> SKIPPING BASE_URL check")

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
    testimage_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    screenshot_dir = os.path.join(datastore_path, str(uuid))
    os.makedirs(screenshot_dir, exist_ok=True)
    with open(os.path.join(screenshot_dir, 'last-screenshot.png'), 'wb') as f:
        f.write(base64.b64decode(testimage_png))

    print(">>>> Notification URL: " + notification_url)

    # Create a watch-level notification profile with the full body template
    watch_notification_body = (
        "BASE URL: {{base_url}}\n"
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
        ":-)"
    )
    watch_profile_uuid = add_notification_profile(
        datastore,
        notification_url=notification_url,
        notification_title="New ChangeDetection.io Notification - {{watch_url}}",
        notification_body=watch_notification_body,
        notification_format='text',
        name="Watch Profile",
    )

    # Update the watch: set tags, title, screenshot, and link the profile
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "my tag, my second tag",
            "title": "my title",
            "headers": "",
            "fetch_backend": "html_requests",
            "notification_screenshot": True,
            "time_between_check_use_default": "y",
            "notification_profiles": watch_profile_uuid,
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Hit the edit page — profile name should appear
    res = client.get(url_for("ui.ui_edit.edit_page", uuid="first"))
    assert b"Watch Profile" in res.data

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

    # Verify what was sent as a notification
    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    os.unlink(os.path.join(datastore_path, "notification.txt"))

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
    # Check the attachment was added
    notification_submission_object = json.loads(notification_submission)
    assert notification_submission_object

    import time
    times_possible = [str(FormattableTimestamp(int(time.time()) - i)) for i in range(15)]
    assert any(t in notification_submission for t in times_possible)

    txt = f"Weekday {FormattableTimestamp(int(time.time()))(format='%A')}"
    assert txt in notification_submission

    # We keep PNG screenshots for now
    assert notification_submission_object['attachments'][0]['filename'] == 'last-screenshot.png'
    assert len(notification_submission_object['attachments'][0]['base64'])
    assert notification_submission_object['attachments'][0]['mimetype'] == 'image/png'
    jpeg_in_attachment = base64.b64decode(notification_submission_object['attachments'][0]['base64'])

    from PIL import Image
    import io
    assert Image.open(io.BytesIO(jpeg_in_attachment))

    if env_base_url:
        logging.debug(">>> BASE_URL checking in notification: %s", env_base_url)
        assert env_base_url in notification_submission
    else:
        logging.debug(">>> Skipping BASE_URL check")

    # This should insert the {current_snapshot}
    set_more_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)
    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    assert "Ohh yeah awesome" in notification_submission

    # Prove that "content constantly being marked as Changed with no Updating causes notification" is not a thing
    os.unlink(os.path.join(datastore_path, "notification.txt"))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert os.path.exists(os.path.join(datastore_path, "notification.txt")) == False

    res = client.get(url_for("settings.notification_logs"))
    assert b'New ChangeDetection.io Notification - ' + test_url.encode('utf-8') in res.data

    # Now unlink the watch profile — it should fall back to the system profile
    set_original_response(datastore_path=datastore_path)
    watch = datastore.data['watching'][uuid]
    watch['notification_profiles'] = []
    watch.commit()

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    with open(os.path.join(datastore_path, "notification.txt"), "r") as f:
        notification_submission = f.read()
    assert "fallback-title" in notification_submission
    assert "fallback-body" in notification_submission

    # cleanup for the next
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )
    clear_notification_profiles(datastore)


def test_notification_urls_jinja2_apprise_integration(client, live_server, measure_memory_usage, datastore_path):

    # https://github.com/caronc/apprise/wiki/Notify_Custom_JSON#header-manipulation
    test_notification_url = "hassio://127.0.0.1/longaccesstoken?verify=no&nid={{watch_uuid}}"
    datastore = client.application.config.get('DATASTORE')

    profile_uuid = add_notification_profile(
        datastore,
        notification_url=test_notification_url,
        notification_body='{ "url" : "{{ watch_url }}", "secret": 444, "somebug": "网站监测 内容更新了", "another": "{{diff|truncate(1500)}}" }',
        notification_format=default_notification_format,
        notification_title="New ChangeDetection.io Notification - {{ watch_url }}  {{diff|truncate(200)}} ",
        name="Jinja2 Integration Test",
    )
    set_system_notification_profile(datastore, profile_uuid)

    # Verify settings page loads OK
    res = client.get(url_for("settings.settings_page"))
    assert res.status_code == 200

    clear_notification_profiles(datastore)


def test_notification_custom_endpoint_and_jinja2(client, live_server, measure_memory_usage, datastore_path):

    # test_endpoint - that sends the contents of a file
    # test_notification_endpoint - that takes a POST and writes it to file (test-datastore/notification.txt)

    # CUSTOM JSON BODY CHECK for POST://
    set_original_response(datastore_path=datastore_path)
    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://') + "?status_code=204&watch_uuid={{ watch_uuid }}&xxx={{ watch_url }}&now={% now 'Europe/London', '%Y-%m-%d' %}&+custom-header=123&+second=hello+world%20%22space%22"

    datastore = client.application.config.get('DATASTORE')
    profile_uuid = add_notification_profile(
        datastore,
        notification_url=test_notification_url,
        notification_body='{ "url" : "{{ watch_url }}", "secret": 444, "somebug": "网站监测 内容更新了" }',
        notification_format=default_notification_format,
        notification_title="New ChangeDetection.io Notification - {{ watch_url }} ",
        name="Custom Endpoint Test",
    )
    set_system_notification_profile(datastore, profile_uuid)

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
    clear_notification_profiles(datastore)


#2510
#@todo run it again as text, html, htmlcolor
def test_global_send_test_notification(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    test_body = 'change detection is cool 网站监测 内容更新了 - {{diff_full}}'
    datastore = client.application.config.get('DATASTORE')

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://') + "?xxx={{ watch_url }}&+custom-header=123"

    profile_uuid = add_notification_profile(
        datastore,
        notification_url=test_notification_url,
        notification_body=test_body,
        notification_format=default_notification_format,
        notification_title="New ChangeDetection.io Notification - {{ watch_url }}",
        name="Global Test Profile",
    )
    set_system_notification_profile(datastore, profile_uuid)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'nice one'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)

    ######### Test using the resolved profiles endpoint
    uuid = next(iter(datastore.data['watching']))
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test", watch_uuid=uuid),
        data={},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        assert 'change detection is cool 网站监测 内容更新了' in x
        if 'html' in default_notification_format:
            assert 'title="Changed into">Example text:' in x
        else:
            assert 'title="Changed into">Example text:' not in x
            assert 'span' not in x
            assert 'Example text:' in x

    os.unlink(os.path.join(datastore_path, "notification.txt"))

    ## Check that 'test' catches errors with a bad profile
    bad_profile_uuid = add_notification_profile(
        datastore,
        notification_url='post://akjsdfkjasdkfjasdkfjasdkjfas232323/should-error',
        name="Bad Profile",
    )
    set_watch_notification_profile(datastore, uuid, bad_profile_uuid)
    # Remove system profile from watch so only bad profile fires
    watch = datastore.data['watching'][uuid]
    watch['notification_profiles'] = [bad_profile_uuid]
    watch.commit()

    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test", watch_uuid=uuid),
        data={},
        follow_redirects=True
    )
    assert res.status_code == 400
    assert (
        b"No address found" in res.data or
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data or
        b"net::ERR_NAME_NOT_RESOLVED" in res.data
    )

    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )

    # When everything is deleted with no watches, expect helpful error
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test"),
        data={},
        follow_redirects=True
    )
    assert res.status_code == 400
    assert b"Error: You must have atleast one watch configured for 'test notification' to work" in res.data

    clear_notification_profiles(datastore)


#2510
def test_single_send_test_notification_on_watch(client, live_server, measure_memory_usage, datastore_path):

    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://') + "?xxx={{ watch_url }}&+custom-header=123"
    test_body = 'change detection is cool 网站监测 内容更新了 - {{diff_full}}\n\nCurrent snapshot: {{current_snapshot}}'
    datastore = client.application.config.get('DATASTORE')

    profile_uuid = add_notification_profile(
        datastore,
        notification_url=test_notification_url,
        notification_body=test_body,
        notification_format=default_notification_format,
        notification_title="New ChangeDetection.io Notification - {{ watch_url }}",
        name="Single Watch Test",
    )
    set_watch_notification_profile(datastore, uuid, profile_uuid)

    ######### Test single-watch notification via resolved profiles
    res = client.post(
        url_for("ui.ui_notification.ajax_callback_send_notification_test", watch_uuid=uuid),
        data={},
        follow_redirects=True
    )

    assert res.status_code != 400
    assert res.status_code != 500

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        x = f.read()
        assert 'change detection is cool 网站监测 内容更新了' in x
        if 'html' in default_notification_format:
            assert 'title="Changed into">Example text:' in x
        else:
            assert 'title="Changed into">Example text:' not in x
            assert 'span' not in x
            assert 'Example text:' in x
        #3720 current_snapshot check
        assert 'Current snapshot: Example text: example test' in x
    os.unlink(os.path.join(datastore_path, "notification.txt"))
    clear_notification_profiles(datastore)


def _test_color_notifications(client, notification_body_token, datastore_path):

    set_original_response(datastore_path=datastore_path)

    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    test_notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', 'post://') + "?xxx={{ watch_url }}&+custom-header=123"

    datastore = client.application.config.get('DATASTORE')
    profile_uuid = add_notification_profile(
        datastore,
        notification_url=test_notification_url,
        notification_body=notification_body_token,
        notification_format="htmlcolor",
        notification_title="New ChangeDetection.io Notification - {{ watch_url }}",
        name="Color Notification Test",
    )
    set_system_notification_profile(datastore, profile_uuid)

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
    clear_notification_profiles(datastore)


# Just checks the format of the colour notifications was correct
def test_html_color_notifications(client, live_server, measure_memory_usage, datastore_path):
    _test_color_notifications(client, '{{diff}}', datastore_path=datastore_path)
    _test_color_notifications(client, '{{diff_full}}', datastore_path=datastore_path)
