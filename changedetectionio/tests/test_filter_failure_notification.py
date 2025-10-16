import os
import time
from flask import url_for
from .util import set_original_response,  wait_for_all_checks, wait_for_notification_endpoint_output
from ..notification import valid_notification_formats


def set_response_with_filter():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div id="nope-doesnt-exist">Some text thats the same</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def run_filter_test(client, live_server, content_filter, app_notification_format):

    # Response WITHOUT the filter ID element
    set_original_response()
    live_server.app.config['DATASTORE'].data['settings']['application']['notification_format'] = app_notification_format

    # Goto the edit page, add our ignore text
    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'post')

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)

    # cleanup for the next
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )
    if os.path.isfile("test-datastore/notification.txt"):
        os.unlink("test-datastore/notification.txt")

    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['consecutive_filter_failures'] == 0, "No filter = No filter failure"

    watch_data = {"notification_urls": notification_url,
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
                                       "Diff Full: {{diff_full}}\n"
                                       "Diff as Patch: {{diff_patch}}\n"
                                       ":-)",
                  "notification_format": "Text",
                  "fetch_backend": "html_requests",
                  "filter_failure_notification_send": 'y',
                  "time_between_check_use_default": "y",
                  "headers": "",
                  "tags": "my tag",
                  "title": "my title 123",
                  "time_between_check-hours": 5,  # So that the queue runner doesnt also put it in
                  "url": test_url,
                  }

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=watch_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['consecutive_filter_failures'] == 0, "No filter = No filter failure"

    # Now add a filter, because recheck hours == 5, ONLY pressing of the [edit] or [recheck all] should trigger
    watch_data['include_filters'] = content_filter
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=watch_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # It should have checked once so far and given this error (because we hit SAVE)

    wait_for_all_checks(client)
    assert not os.path.isfile("test-datastore/notification.txt")

    # Hitting [save] would have triggered a recheck, and we have a filter, so this would be ONE failure
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['consecutive_filter_failures'] == 1, "Should have been checked once"

    # recheck it up to just before the threshold, including the fact that in the previous POST it would have rechecked (and incremented)
    # Add 4 more checks
    checked = 0
    ATTEMPT_THRESHOLD_SETTING = live_server.app.config['DATASTORE'].data['settings']['application'].get('filter_failure_notification_threshold_attempts', 0)
    for i in range(0, ATTEMPT_THRESHOLD_SETTING - 2):
        checked += 1
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        res = client.get(url_for("watchlist.index"))
        assert b'Warning, no filters were found' in res.data
        assert not os.path.isfile("test-datastore/notification.txt")
        time.sleep(1)
        
    assert live_server.app.config['DATASTORE'].data['watching'][uuid]['consecutive_filter_failures'] == 5

    time.sleep(2)
    # One more check should trigger the _FILTER_FAILURE_THRESHOLD_ATTEMPTS_DEFAULT threshold
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    wait_for_notification_endpoint_output()

    # Now it should exist and contain our "filter not found" alert
    assert os.path.isfile("test-datastore/notification.txt")
    with open("test-datastore/notification.txt", 'r') as f:
        notification = f.read()

    assert 'Your configured CSS/xPath filters' in notification


    # Text (or HTML conversion) markup to make the notifications a little nicer should have worked
    if app_notification_format.startswith('html'):
        # apprise should have used sax-escape (&#39; instead of &quot;, " etc), lets check it worked

        from apprise.conversion import convert_between
        from apprise.common import NotifyFormat
        escaped_filter = convert_between(NotifyFormat.TEXT, NotifyFormat.HTML, content_filter)

        assert escaped_filter in notification or escaped_filter.replace('&quot;', '&#34;') in notification
        assert 'a href="' in notification # Quotes should still be there so the link works

    else:
        assert 'a href' not in notification
        assert content_filter in notification

    # Remove it and prove that it doesn't trigger when not expected
    # It should register a change, but no 'filter not found'
    os.unlink("test-datastore/notification.txt")
    set_response_with_filter()

    # Try several times, it should NOT have 'filter not found'
    for i in range(0, ATTEMPT_THRESHOLD_SETTING + 2):
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

    wait_for_notification_endpoint_output()
    # It should have sent a notification, but..
    assert os.path.isfile("test-datastore/notification.txt")
    # but it should not contain the info about a failed filter (because there was none in this case)
    with open("test-datastore/notification.txt", 'r') as f:
        notification = f.read()
    assert not 'CSS/xPath filter was not present in the page' in notification

    # Re #1247 - All tokens got replaced correctly in the notification
    assert uuid in notification

    # cleanup for the next
    client.get(
        url_for("ui.form_delete", uuid="all"),
        follow_redirects=True
    )
    os.unlink("test-datastore/notification.txt")


def test_check_include_filters_failure_notification(client, live_server, measure_memory_usage):
    #   #  live_server_setup(live_server) # Setup on conftest per function
    run_filter_test(client=client, live_server=live_server, content_filter='#nope-doesnt-exist', app_notification_format=valid_notification_formats.get('HTML Color'))
    # Check markup send conversion didnt affect plaintext preference
    run_filter_test(client=client, live_server=live_server, content_filter='#nope-doesnt-exist', app_notification_format=valid_notification_formats.get('Text'))

def test_check_xpath_filter_failure_notification(client, live_server, measure_memory_usage):
    #   #  live_server_setup(live_server) # Setup on conftest per function
    run_filter_test(client=client, live_server=live_server, content_filter='//*[@id="nope-doesnt-exist"]', app_notification_format=valid_notification_formats.get('HTML Color'))

# Test that notification is never sent

def test_basic_markup_from_text(client, live_server, measure_memory_usage):
    # Test the notification error templates convert to HTML if needed (link activate)
    from ..notification.handler import markup_text_links_to_html
    x = markup_text_links_to_html("hello https://google.com")
    assert 'a href' in x
