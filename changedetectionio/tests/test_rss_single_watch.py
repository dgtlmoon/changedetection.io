#!/usr/bin/env python3

import time
import os
import xml.etree.ElementTree as ET
from flask import url_for

from build.lib.changedetectionio.tests.test_group import set_modified_response
from .restock.test_restock import set_original_response
from .util import live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, extract_UUID_from_client, delete_all_watches
from ..notification import default_notification_format


# Watch with no change should not break the output
def test_rss_feed_empty(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    rss_token = extract_rss_token_from_UI(client)
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    # Request RSS feed for the single watch
    res = client.get(
        url_for("rss.rss_single_watch", uuid=uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 400
    assert b'does not have enough history snapshots to show' in res.data

def test_rss_single_watch_order(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that single watch RSS feed shows changes in correct order (newest first).
    """

    # Create initial content
    def set_response(datastore_path, version):
        test_return_data = f"""<html>
           <body>
         <p>Version {version} content</p>
         </body>
         </html>
        """
        with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
            f.write(test_return_data)

    # Start with version 1
    set_response(datastore_path, 1)

    # Add a watch
    test_url = url_for('test_endpoint', _external=True) + "?order_test=1"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": 'test-tag'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Get the watch UUID
    watch_uuid = extract_UUID_from_client(client)

    # Wait for initial check
    wait_for_all_checks(client)

    # Create multiple versions by triggering changes
    for version in range(2, 6):  # Create versions 2, 3, 4, 5
        set_response(datastore_path, version)
        res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        time.sleep(0.5)  # Small delay to ensure different timestamps

    # Get RSS token
    rss_token = extract_rss_token_from_UI(client)

    # Request RSS feed for the single watch
    res = client.get(
        url_for("rss.rss_single_watch", uuid=watch_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )

    # Should return valid RSS
    assert res.status_code == 200
    assert b"<?xml" in res.data or b"<rss" in res.data

    # Parse the RSS/XML
    root = ET.fromstring(res.data)

    # Find all items (RSS 2.0) or entries (Atom)
    items = root.findall('.//item')
    if not items:
        items = root.findall('.//{http://www.w3.org/2005/Atom}entry')

    # Should have multiple items
    assert len(items) >= 3, f"Expected at least 3 items, got {len(items)}"

    # Get the descriptions/content from first 3 items
    descriptions = []
    for item in items[:3]:
        # Try RSS format first
        desc = item.findtext('description')
        if not desc:
            # Try Atom format
            content_elem = item.find('{http://www.w3.org/2005/Atom}content')
            if content_elem is not None:
                desc = content_elem.text
        descriptions.append(desc if desc else "")

    print(f"First item content: {descriptions[0][:100] if descriptions[0] else 'None'}")
    print(f"Second item content: {descriptions[1][:100] if descriptions[1] else 'None'}")
    print(f"Third item content: {descriptions[2][:100] if descriptions[2] else 'None'}")

    # The FIRST item should contain the NEWEST change (Version 5)
    # The SECOND item should contain Version 4
    # The THIRD item should contain Version 3
    assert b"Version 5" in descriptions[0].encode() or "Version 5" in descriptions[0], \
        f"First item should show newest change (Version 5), but got: {descriptions[0][:200]}"

    # Verify the order is correct
    assert b"Version 4" in descriptions[1].encode() or "Version 4" in descriptions[1], \
        f"Second item should show Version 4, but got: {descriptions[1][:200]}"

    assert b"Version 3" in descriptions[2].encode() or "Version 3" in descriptions[2], \
        f"Third item should show Version 3, but got: {descriptions[2][:200]}"

    # Clean up
    delete_all_watches(client)


def test_rss_categories_from_tags(client, live_server, measure_memory_usage, datastore_path):
    """
    Test that RSS feeds include category tags from watch tags.
    """

    # Create initial content
    test_return_data = """<html>
       <body>
     <p>Test content for RSS categories</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    # Create some tags first
    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "Security"},
        follow_redirects=True
    )

    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "Python"},
        follow_redirects=True
    )

    res = client.post(
        url_for("tags.form_tag_add"),
        data={"name": "Tech News"},
        follow_redirects=True
    )

    # Add a watch with tags
    test_url = url_for('test_endpoint', _external=True) + "?category_test=1"
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "Security, Python, Tech News"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    # Get the watch UUID
    watch_uuid = extract_UUID_from_client(client)

    # Wait for initial check
    wait_for_all_checks(client)

    # Trigger one change
    test_return_data_v2 = """<html>
       <body>
     <p>Updated content for RSS categories</p>
     </body>
     </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data_v2)

    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Get RSS token
    rss_token = extract_rss_token_from_UI(client)

    # Test 1: Check single watch RSS feed
    res = client.get(
        url_for("rss.rss_single_watch", uuid=watch_uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b"<?xml" in res.data or b"<rss" in res.data

    # Parse the RSS/XML
    root = ET.fromstring(res.data)

    # Find all items
    items = root.findall('.//item')
    assert len(items) >= 1, "Expected at least 1 item in RSS feed"

    # Get categories from first item
    categories = [cat.text for cat in items[0].findall('category')]

    print(f"Found categories in single watch RSS: {categories}")

    # Should have all three categories
    assert "Security" in categories, f"Expected 'Security' category, got: {categories}"
    assert "Python" in categories, f"Expected 'Python' category, got: {categories}"
    assert "Tech News" in categories, f"Expected 'Tech News' category, got: {categories}"
    assert len(categories) == 3, f"Expected 3 categories, got {len(categories)}: {categories}"

    # Test 2: Check main RSS feed
    res = client.get(
        url_for("rss.feed", token=rss_token, _external=True),
        follow_redirects=True
    )
    assert res.status_code == 200

    root = ET.fromstring(res.data)
    items = root.findall('.//item')
    assert len(items) >= 1, "Expected at least 1 item in main RSS feed"

    # Get categories from first item in main feed
    categories = [cat.text for cat in items[0].findall('category')]

    print(f"Found categories in main RSS feed: {categories}")

    # Should have all three categories
    assert "Security" in categories, f"Expected 'Security' category in main feed, got: {categories}"
    assert "Python" in categories, f"Expected 'Python' category in main feed, got: {categories}"
    assert "Tech News" in categories, f"Expected 'Tech News' category in main feed, got: {categories}"

    # Test 3: Check tag-specific RSS feed (should also have categories)
    # Get the tag UUID for "Security" and verify the tag feed also has categories
    from .util import get_UUID_for_tag_name
    security_tag_uuid = get_UUID_for_tag_name(client, name="Security")

    if security_tag_uuid:
        res = client.get(
            url_for("rss.rss_tag_feed", tag_uuid=security_tag_uuid, token=rss_token, _external=True),
            follow_redirects=True
        )
        assert res.status_code == 200

        root = ET.fromstring(res.data)
        items = root.findall('.//item')

        if len(items) >= 1:
            categories = [cat.text for cat in items[0].findall('category')]
            print(f"Found categories in tag RSS feed: {categories}")

            # Should still have all three categories
            assert "Security" in categories, f"Expected 'Security' category in tag feed, got: {categories}"
            assert "Python" in categories, f"Expected 'Python' category in tag feed, got: {categories}"
            assert "Tech News" in categories, f"Expected 'Tech News' category in tag feed, got: {categories}"

    # Clean up
    delete_all_watches(client)


# RSS <description> should follow Main Settings -> Tag/Group -> Watch in that order of priority if set.
def test_rss_single_watch_follow_notification_body(client, live_server, measure_memory_usage, datastore_path):
    rss_token = extract_rss_token_from_UI(client)


    res = client.post(
        url_for("settings.settings_page"),
        data={
              "application-fetch_backend": "html_requests",
              "application-minutes_between_check": 180,
              "application-notification_body": 'Boo yeah hello from main settings notification body<br>\nTitle: {{ watch_title }} changed',
              "application-notification_format": default_notification_format,
              "application-rss_template_type" : 'notification_body',
              "application-notification_urls": "",

              },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data


    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, tag="RSS-Custom")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)


    # Request RSS feed for the single watch
    res = client.get(
        url_for("rss.rss_single_watch", uuid=uuid, token=rss_token, _external=True),
        follow_redirects=True
    )

    # Should return valid RSS
    assert res.status_code == 200
    assert b"<?xml" in res.data or b"<rss" in res.data

    # Check it took the notification body from main settings ####
    item_description = ET.fromstring(res.data).findall('.//item')[0].findtext('description')
    assert "Boo yeah hello from main settings notification body" in item_description
    assert "Title: http://" in item_description


    ## Edit the tag notification_body, it should cascade up and become the RSS output
    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid="first"),
        data={"name": "rss-custom",
              "notification_body": 'Hello from the group/tag level'},
        follow_redirects=True
    )
    assert b"Updated" in res.data
    res = client.get(
        url_for("rss.rss_single_watch", uuid=uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    item_description = ET.fromstring(res.data).findall('.//item')[0].findtext('description')
    assert 'Hello from the group/tag level' in item_description

    # Override notification body at watch level and check ####
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"notification_body": "RSS body description set from watch level at notification body - {{ watch_title }}",
              "url": test_url,
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    res = client.get(
        url_for("rss.rss_single_watch", uuid=uuid, token=rss_token, _external=True),
        follow_redirects=True
    )
    item_description = ET.fromstring(res.data).findall('.//item')[0].findtext('description')
    assert 'RSS body description set from watch level at notification body - http://' in item_description
    delete_all_watches(client)