#!/usr/bin/env python3

# https://www.reddit.com/r/selfhosted/comments/wa89kp/comment/ii3a4g7/?context=3
import os
import time
from flask import url_for
from .util import set_original_response, live_server_setup, wait_for_notification_endpoint_output
from changedetectionio.model import App


def set_response_without_filter(datastore_path):
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def set_response_with_filter(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div class="ticket-available">Ticket now on sale!</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None

def test_filter_doesnt_exist_then_exists_should_get_notification(client, live_server, measure_memory_usage, datastore_path):
#  Filter knowingly doesn't exist, like someone setting up a known filter to see if some cinema tickets are on sale again
#  And the page has that filter available
#  Then I should get a notification

   #  live_server_setup(live_server) # Setup on conftest per function

    # Give the endpoint time to spin up
    time.sleep(1)
    set_response_without_filter(datastore_path=datastore_path)
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)

    # Give the thread time to pick up the first version
    time.sleep(3)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    url = url_for('test_notification_endpoint', _external=True)
    notification_url = url.replace('http', 'json')

    print(">>>> Notification URL: " + notification_url)

    # Just a regular notification setting, this will be used by the special 'filter not found' notification
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
                                                   "Diff Full: {{diff_full}}\n"
                                                   "Diff as Patch: {{diff_patch}}\n"
                                                   ":-)",
                              "notification_format": 'text'}

    notification_form_data.update({
        "url": test_url,
        "tags": "my tag",
        "title": "my title",
        "headers": "",
        # preprended with extra filter that intentionally doesn't match any entry,
        # notification should still be sent even if first filter does not match (PR#3516)
        "include_filters": ".non-matching-selector\n.ticket-available",
        "fetch_backend": "html_requests",
        "time_between_check_use_default": "y"})

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data=notification_form_data,
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    # Shouldn't exist, shouldn't have fired
    assert not os.path.isfile(os.path.join(datastore_path, "notification.txt"))
    # Now the filter should exist
    set_response_with_filter(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_notification_endpoint_output(datastore_path=datastore_path)

    assert os.path.isfile(os.path.join(datastore_path, "notification.txt"))

    with open(os.path.join(datastore_path, "notification.txt"), 'r') as f:
        notification = f.read()

    assert 'Ticket now on sale' in notification
    os.unlink(os.path.join(datastore_path, "notification.txt"))
