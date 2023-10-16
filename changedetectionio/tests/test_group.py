#!/usr/bin/python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, get_UUID_for_tag_name, extract_UUID_from_client
import os


def test_setup(client, live_server):
    live_server_setup(live_server)

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p id="only-this">Should be only this</p>
     <br>
     <p id="not-this">And never this</p>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_modified_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p id="only-this">Should be REALLY only this</p>
     <br>
     <p id="not-this">And never this</p>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def test_setup_group_tag(client, live_server):
    #live_server_setup(live_server)
    set_original_response()

    # Add a tag with some config, import a tag and it should roughly work
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "test-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    assert b"test-tag" in res.data

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid="first"),
        data={"name": "test-tag",
              "include_filters": '#only-this',
              "subtractive_selectors": '#not-this'},
        follow_redirects=True
    )
    assert b"Updated" in res.data
    tag_uuid = get_UUID_for_tag_name(client, name="test-tag")
    res = client.get(
        url_for("tags.form_tag_edit", uuid="first")
    )
    assert b"#only-this" in res.data
    assert b"#not-this" in res.data

    # Tag should be setup and ready, now add a watch

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url + "?first-imported=1 test-tag, extra-import-tag"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.get(url_for("index"))
    assert b'import-tag' in res.data
    assert b'extra-import-tag' in res.data

    res = client.get(
        url_for("tags.tags_overview_page"),
        follow_redirects=True
    )
    assert b'import-tag' in res.data
    assert b'extra-import-tag' in res.data

    wait_for_all_checks(client)

    res = client.get(url_for("index"))
    assert b'Warning, no filters were found' not in res.data

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'Should be only this' in res.data
    assert b'And never this' not in res.data


    # RSS Group tag filter
    # An extra one that should be excluded
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url + "?should-be-excluded=1 some-tag"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    set_modified_response()
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    rss_token = extract_rss_token_from_UI(client)
    res = client.get(
        url_for("rss", token=rss_token, tag="extra-import-tag", _external=True),
        follow_redirects=True
    )
    assert b"should-be-excluded" not in res.data
    assert res.status_code == 200
    assert b"first-imported=1" in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_tag_import_singular(client, live_server):
    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url + " test-tag, test-tag\r\n"+ test_url + "?x=1 test-tag, test-tag\r\n"},
        follow_redirects=True
    )
    assert b"2 Imported" in res.data

    res = client.get(
        url_for("tags.tags_overview_page"),
        follow_redirects=True
    )
    # Should be only 1 tag because they both had the same
    assert res.data.count(b'test-tag') == 1
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_tag_add_in_ui(client, live_server):
    #live_server_setup(live_server)
#
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "new-test-tag"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    assert b"new-test-tag" in res.data

    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_group_tag_notification(client, live_server):
    #live_server_setup(live_server)
    set_original_response()

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": 'test-tag, other-tag'},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http', 'json')
    notification_form_data = {"notification_urls": notification_url,
                              "notification_title": "New GROUP TAG ChangeDetection.io Notification - {{watch_url}}",
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
                              "notification_format": "Text",
                              "title": "test-tag"}

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=get_UUID_for_tag_name(client, name="test-tag")),
        data=notification_form_data,
        follow_redirects=True
    )
    assert b"Updated" in res.data

    wait_for_all_checks(client)

    set_modified_response()
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    time.sleep(3)

    assert os.path.isfile("test-datastore/notification.txt")

    # Verify what was sent as a notification, this file should exist
    with open("test-datastore/notification.txt", "r") as f:
        notification_submission = f.read()
    os.unlink("test-datastore/notification.txt")

    # Did we see the URL that had a change, in the notification?
    # Diff was correctly executed
    assert test_url in notification_submission
    assert ':-)' in notification_submission
    assert "Diff Full: Some initial text" in notification_submission
    assert "New GROUP TAG ChangeDetection.io" in notification_submission
    assert "test-tag" in notification_submission
    assert "other-tag" in notification_submission

    #@todo Test that multiple notifications fired
    #@todo Test that each of multiple notifications with different settings
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_limit_tag_ui(client, live_server):
    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)
    urls=[]

    for i in range(20):
        urls.append(test_url+"?x="+str(i)+" test-tag")

    for i in range(20):
        urls.append(test_url+"?non-grouped="+str(i))

    res = client.post(
        url_for("import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )

    assert b"40 Imported" in res.data

    res = client.get(url_for("index"))
    assert b'test-tag' in res.data

    # All should be here
    assert res.data.count(b'processor-text_json_diff') == 40

    tag_uuid = get_UUID_for_tag_name(client, name="test-tag")

    res = client.get(url_for("index", tag=tag_uuid))

    # Just a subset should be here
    assert b'test-tag' in res.data
    assert res.data.count(b'processor-text_json_diff') == 20
    assert b"object at" not in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data
def test_clone_tag_on_import(client, live_server):
    #live_server_setup(live_server)
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url + " test-tag, another-tag\r\n"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    res = client.get(url_for("index"))
    assert b'test-tag' in res.data
    assert b'another-tag' in res.data

    watch_uuid = extract_UUID_from_client(client)
    res = client.get(url_for("form_clone", uuid=watch_uuid), follow_redirects=True)

    assert b'Cloned' in res.data
    # 2 times plus the top link to tag
    assert res.data.count(b'test-tag') == 3
    assert res.data.count(b'another-tag') == 3
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_clone_tag_on_quickwatchform_add(client, live_server):
    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": ' test-tag, another-tag      '},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    res = client.get(url_for("index"))
    assert b'test-tag' in res.data
    assert b'another-tag' in res.data

    watch_uuid = extract_UUID_from_client(client)
    res = client.get(url_for("form_clone", uuid=watch_uuid), follow_redirects=True)

    assert b'Cloned' in res.data
    # 2 times plus the top link to tag
    assert res.data.count(b'test-tag') == 3
    assert res.data.count(b'another-tag') == 3
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data
