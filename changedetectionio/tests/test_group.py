#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, get_UUID_for_tag_name, extract_UUID_from_client
import os


# def test_setup(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function

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

def test_setup_group_tag(client, live_server, measure_memory_usage):
    
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
        url_for("imports.import_page"),
        data={"urls": test_url + "?first-imported=1 test-tag, extra-import-tag"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.get(url_for("watchlist.index"))
    assert b'import-tag' in res.data
    assert b'extra-import-tag' in res.data

    res = client.get(
        url_for("tags.tags_overview_page"),
        follow_redirects=True
    )
    assert b'import-tag' in res.data
    assert b'extra-import-tag' in res.data

    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'Warning, no filters were found' not in res.data

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'Should be only this' in res.data
    assert b'And never this' not in res.data

    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        follow_redirects=True
    )
    # 2307 the UI notice should appear in the placeholder
    assert b'WARNING: Watch has tag/groups set with special filters' in res.data

    # RSS Group tag filter
    # An extra one that should be excluded
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url + "?should-be-excluded=1 some-tag"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    set_modified_response()
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    rss_token = extract_rss_token_from_UI(client)
    res = client.get(
        url_for("rss.feed", token=rss_token, tag="extra-import-tag", _external=True),
        follow_redirects=True
    )
    assert b"should-be-excluded" not in res.data
    assert res.status_code == 200
    assert b"first-imported=1" in res.data
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_tag_import_singular(client, live_server, measure_memory_usage):
    

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
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
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_tag_add_in_ui(client, live_server, measure_memory_usage):
    
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

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_group_tag_notification(client, live_server, measure_memory_usage):
    
    set_original_response()

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
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
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
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
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_limit_tag_ui(client, live_server, measure_memory_usage):

    test_url = url_for('test_random_content_endpoint', _external=True)

    # A space can label the tag, only the first one will have a tag
    client.post(
        url_for("imports.import_page"),
        data={"urls": f"{test_url} test-tag\r\n{test_url}"},
        follow_redirects=True
    )
    tag_uuid = get_UUID_for_tag_name(client, name="test-tag")
    assert tag_uuid

    res = client.get(url_for("watchlist.index"))
    assert b'test-tag' in res.data
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be both unviewed
    res = client.get(url_for("watchlist.index"))
    assert res.data.count(b' unviewed ') == 2


    # Now we recheck only the tag
    client.get(url_for('ui.mark_all_viewed', tag=tag_uuid), follow_redirects=True)
    wait_for_all_checks(client)

    with open('/tmp/fuck.html', 'wb') as f:
        f.write(res.data)
    # Should be only 1 unviewed
    res = client.get(url_for("watchlist.index"))
    assert res.data.count(b' unviewed ') == 1


    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data

def test_clone_tag_on_import(client, live_server, measure_memory_usage):
    
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url + " test-tag, another-tag\r\n"},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    res = client.get(url_for("watchlist.index"))
    assert b'test-tag' in res.data
    assert b'another-tag' in res.data

    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    res = client.get(url_for("ui.form_clone", uuid=watch_uuid), follow_redirects=True)

    assert b'Cloned' in res.data
    res = client.get(url_for("watchlist.index"))
    # 2 times plus the top link to tag
    assert res.data.count(b'test-tag') == 3
    assert res.data.count(b'another-tag') == 3
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_clone_tag_on_quickwatchform_add(client, live_server, measure_memory_usage):
    

    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ' test-tag, another-tag      '},
        follow_redirects=True
    )

    assert b"Watch added" in res.data

    res = client.get(url_for("watchlist.index"))
    assert b'test-tag' in res.data
    assert b'another-tag' in res.data

    watch_uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    res = client.get(url_for("ui.form_clone", uuid=watch_uuid), follow_redirects=True)
    assert b'Cloned' in res.data

    res = client.get(url_for("watchlist.index"))
    # 2 times plus the top link to tag
    assert res.data.count(b'test-tag') == 3
    assert res.data.count(b'another-tag') == 3
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    res = client.get(url_for("tags.delete_all"), follow_redirects=True)
    assert b'All tags deleted' in res.data

def test_order_of_filters_tag_filter_and_watch_filter(client, live_server, measure_memory_usage):

    # Add a tag with some config, import a tag and it should roughly work
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "test-tag-keep-order"},
        follow_redirects=True
    )
    assert b"Tag added" in res.data
    assert b"test-tag-keep-order" in res.data
    tag_filters = [
            '#only-this', # duplicated filters
            '#only-this',
            '#only-this',
            '#only-this',
            ]

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid="first"),
        data={"name": "test-tag-keep-order",
              "include_filters": '\n'.join(tag_filters) },
        follow_redirects=True
    )
    assert b"Updated" in res.data
    tag_uuid = get_UUID_for_tag_name(client, name="test-tag-keep-order")
    res = client.get(
        url_for("tags.form_tag_edit", uuid="first")
    )
    assert b"#only-this" in res.data


    d = """<html>
       <body>
     Some initial text<br>
     <p id="only-this">And 1 this</p>
     <br>
     <p id="not-this">And 2 this</p>
     <p id="">And 3 this</p><!--/html/body/p[3]/-->
     <p id="">And 4 this</p><!--/html/body/p[4]/-->
     <p id="">And 5 this</p><!--/html/body/p[5]/-->
     <p id="">And 6 this</p><!--/html/body/p[6]/-->
     <p id="">And 7 this</p><!--/html/body/p[7]/-->
     <p id="">And 8 this</p><!--/html/body/p[8]/-->
     <p id="">And 9 this</p><!--/html/body/p[9]/-->
     <p id="">And 10 this</p><!--/html/body/p[10]/-->
     <p id="">And 11 this</p><!--/html/body/p[11]/-->
     <p id="">And 12 this</p><!--/html/body/p[12]/-->
     <p id="">And 13 this</p><!--/html/body/p[13]/-->
     <p id="">And 14 this</p><!--/html/body/p[14]/-->
     <p id="not-this">And 15 this</p><!--/html/body/p[15]/-->
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(d)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    filters = [
            '/html/body/p[3]',
            '/html/body/p[4]',
            '/html/body/p[5]',
            '/html/body/p[6]',
            '/html/body/p[7]',
            '/html/body/p[8]',
            '/html/body/p[9]',
            '/html/body/p[10]',
            '/html/body/p[11]',
            '/html/body/p[12]',
            '/html/body/p[13]', # duplicated tags
            '/html/body/p[13]',
            '/html/body/p[13]',
            '/html/body/p[13]',
            '/html/body/p[13]',
            '/html/body/p[14]',
            ]

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": '\n'.join(filters),
            "url": test_url,
            "tags": "test-tag-keep-order",
            "headers": "",
            'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"And 1 this" in res.data  # test-tag-keep-order

    a_tag_filter_check = b'And 1 this' #'#only-this' of tag_filters
    # check there is no duplication of tag_filters
    assert res.data.count(a_tag_filter_check) == 1, f"duplicated filters didn't removed {res.data.count(a_tag_filter_check)} of {a_tag_filter_check} in {res.data=}"

    a_filter_check = b"And 13 this" # '/html/body/p[13]'
    # check there is no duplication of filters
    assert res.data.count(a_filter_check) == 1, f"duplicated filters didn't removed. {res.data.count(a_filter_check)} of {a_filter_check} in {res.data=}"

    a_filter_check_not_include = b"And 2 this" # '/html/body/p[2]'
    assert a_filter_check_not_include not in res.data

    checklist = [
            b"And 3 this",
            b"And 4 this",
            b"And 5 this",
            b"And 6 this",
            b"And 7 this",
            b"And 8 this",
            b"And 9 this",
            b"And 10 this",
            b"And 11 this",
            b"And 12 this",
            b"And 13 this",
            b"And 14 this",
            b"And 1 this", # result of filter from tag.
            ]
    # check whether everything a user requested is there
    for test in checklist:
        assert test in res.data

    # check whether everything a user requested is in order of filters.
    n = 0
    for test in checklist:
        t_index = res.data[n:].find(test)
        # if the text is not searched, return -1.
        assert t_index >= 0, f"""failed because {test=} not in {res.data[n:]=}
#####################
Looks like some feature changed the order of result of filters.
#####################
the {test} appeared before. {test in res.data[:n]=}
{res.data[:n]=}
        """
        n += t_index + len(test)

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
