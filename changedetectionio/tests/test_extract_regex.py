#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks, delete_all_watches
import os

from ..html_tools import *


def set_original_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>     
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def set_modified_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div class="changetext">Some text that did change ( 1000 online <br> 80 guests<br>  2000 online )</div>
     <div class="changetext">SomeCase insensitive 3456</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    return None


def set_multiline_response(datastore_path):
    test_return_data = """<html>
       <body>
     
     <p>Something <br>
        across 6 billion multiple<br>
        lines
     </p>
     
     <div>aaand something lines</div>
     <br>
     <div>and this should be</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    return None


# def test_setup(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function

def test_check_filter_multiline(client, live_server, measure_memory_usage, datastore_path):
   ##  live_server_setup(live_server) # Setup on conftest per function
    set_multiline_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": '',
              # Test a regex and a plaintext
              'extract_text': '/something.+?6 billion.+?lines/si\r\nand this should be',
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"
              },
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))

    # Issue 1828
    assert b'not at the start of the expression' not in res.data

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )
    # Plaintext that doesnt look like a regex should match also
    assert b'and this should be' in res.data

    assert b'Something' in res.data
    assert b'across 6 billion multiple' in res.data
    assert b'lines' in res.data

    # but the last one, which also says 'lines' shouldnt be here (non-greedy match checking)
    assert b'aaand something lines' not in res.data

def test_check_filter_and_regex_extract(client, live_server, measure_memory_usage, datastore_path):
    
    include_filters = ".changetext"

    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": include_filters,
              'extract_text': '/\d+ online/\r\n/\d+ guests/\r\n/somecase insensitive \d+/i\r\n/somecase insensitive (345\d)/i\r\n/issue1828.+?2022/i',
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"
              },
        follow_redirects=True
    )

    assert b"Updated watch." in res.data


    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    #issue 1828
    assert b'not at the start of the expression' not in res.data

    #  Make a change
    set_modified_response(datastore_path=datastore_path)

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should have 'has-unread-changes' still
    # Because it should be looking at only that 'sametext' id
    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'1000 online' in res.data

    # All regex matching should be here
    assert b'2000 online' in res.data

    # Both regexs should be here
    assert b'80 guests' in res.data

    # Regex with flag handling should be here
    assert b'SomeCase insensitive 3456' in res.data

    # Singular group from /somecase insensitive (345\d)/i
    assert b'3456' in res.data

    # Regex with multiline flag handling should be here

    # Should not be here
    assert b'Some text that did change' not in res.data



def test_regex_error_handling(client, live_server, measure_memory_usage, datastore_path):

    

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    time.sleep(0.2)
    ### test regex error handling
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"extract_text": '/something bad\d{3/XYZ',
              "url": test_url,
              "fetch_backend": "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b'is not a valid regular expression.' in res.data

    delete_all_watches(client)


def test_extract_lines_containing(client, live_server, measure_memory_usage, datastore_path):
    """Test the 'extract_lines_containing' filter keeps only lines with matching substrings."""

    test_return_data = """<html>
       <body>
         <p>Current temperature: 21 celsius</p>
         <p>Humidity: 55%</p>
         <p>Wind speed: 10 km/h</p>
         <p>Feels like: 19 celsius</p>
         <p>UV index: 3</p>
       </body>
       </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            'extract_lines_containing': 'celsius',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)

    # Lines containing 'celsius' should be present
    assert b'celsius' in res.data
    # Lines without 'celsius' should be excluded
    assert b'Humidity' not in res.data
    assert b'Wind speed' not in res.data
    assert b'UV index' not in res.data

    delete_all_watches(client)


def test_extract_lines_containing_case_insensitive(client, live_server, measure_memory_usage, datastore_path):
    """Test that extract_lines_containing is case-insensitive."""

    test_return_data = """<html>
       <body>
         <p>PRICE: $99.99</p>
         <p>Price drops to $79.99</p>
         <p>Stock: Available</p>
         <p>price history shows decline</p>
       </body>
       </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            'extract_lines_containing': 'price',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)

    # All three price lines (different cases) should match
    assert b'$99.99' in res.data
    assert b'$79.99' in res.data
    assert b'price history' in res.data
    # Non-price line should be excluded
    assert b'Stock' not in res.data

    delete_all_watches(client)


def test_extract_lines_containing_multiple_terms(client, live_server, measure_memory_usage, datastore_path):
    """Test that multiple extract_lines_containing entries act as OR (keep line if any term matches)."""

    test_return_data = """<html>
       <body>
         <p>Temperature: 21 celsius</p>
         <p>Humidity: 55%</p>
         <p>Wind speed: 10 km/h</p>
         <p>Rain chance: 20%</p>
       </body>
       </html>
    """
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            'extract_lines_containing': 'celsius\r\nhumidity',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)

    assert b'celsius' in res.data
    assert b'Humidity' in res.data
    # Wind and Rain lines should be excluded
    assert b'Wind speed' not in res.data
    assert b'Rain chance' not in res.data

    delete_all_watches(client)


def test_extract_lines_containing_with_ignore_text(client, live_server, measure_memory_usage, datastore_path):
    """
    extract_lines_containing narrows to matching lines; ignore_text then suppresses specific
    lines from triggering change detection (they remain visible but don't affect the checksum).

    Filters are set BEFORE the first check so the filtered+ignored checksum is the baseline
    from the very start — no race between a forced-recheck and the next content write.
    """
    initial_data = """<html><body>
      <p>Temperature: 21 celsius</p>
      <p>Feels like: 19 celsius</p>
      <p>Humidity: 55%</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(initial_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'paused': True})

    # Set filters BEFORE the first check so the baseline is always filtered+ignored.
    # (Setting them after an initial unfiltered check creates a race: the forced recheck
    #  that updates previous_md5 must complete before the next content write, which is
    #  timing-sensitive and fails intermittently on slower systems / Python 3.14.)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            'extract_lines_containing': 'celsius',
            'ignore_text': 'Feels like',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    # First check — establishes filtered+ignored baseline. previous_md5 was False so
    # a change is always detected here; mark_all_viewed clears it before we assert.
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Sanity: preview should only show celsius lines
    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)
    assert b'celsius' in res.data
    assert b'Humidity' not in res.data

    # Change ONLY the ignored "Feels like" line — should NOT trigger a change
    changed_data = """<html><body>
      <p>Temperature: 21 celsius</p>
      <p>Feels like: 17 celsius</p>
      <p>Humidity: 55%</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(changed_data)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data, "Changing an ignored line should not trigger a change notification"

    client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    time.sleep(1)

    # Change the non-ignored celsius line — SHOULD trigger
    triggered_data = """<html><body>
      <p>Temperature: 30 celsius</p>
      <p>Feels like: 17 celsius</p>
      <p>Humidity: 55%</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(triggered_data)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data,  "Changing a non-ignored line should trigger a change notification"

    delete_all_watches(client)


def test_extract_lines_containing_with_extract_text_regex(client, live_server, measure_memory_usage, datastore_path):
    """
    extract_lines_containing first narrows to relevant lines, then extract_text regex
    pulls specific tokens from those lines — verifying correct pipeline ordering.
    """
    test_return_data = """<html><body>
      <p>Widget price: $49.99 each</p>
      <p>Gadget price: $129.00 each</p>
      <p>Latest news: price index up 2%</p>
      <p>Stock count: 150 units</p>
      <p>Shipping cost: $5.99</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            # Step 1: keep lines containing "price" (excludes Stock count and Shipping cost)
            'extract_lines_containing': 'price',
            # Step 2: from those lines extract only dollar amounts
            'extract_text': r'/\$[\d.]+/',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)

    # Dollar amounts from price lines should be extracted
    assert b'$49.99' in res.data
    assert b'$129.00' in res.data
    # "price index up 2%" has no dollar amount — nothing extracted from that line
    # "Shipping cost" line was excluded by extract_lines_containing before regex ran
    assert b'$5.99' not in res.data
    # Raw line text should not appear — regex replaced it with just the match
    assert b'Widget' not in res.data
    assert b'Stock count' not in res.data

    delete_all_watches(client)


def test_extract_lines_containing_with_include_filters_css(client, live_server, measure_memory_usage, datastore_path):
    """
    CSS include_filters narrows the HTML first; extract_lines_containing then filters
    within that already-reduced text — verifying correct pipeline ordering.
    """
    test_return_data = """<html><body>
      <div class="weather">
        <p>Temperature: 21 celsius</p>
        <p>Humidity: 60%</p>
        <p>Wind: 15 km/h</p>
      </div>
      <div class="news">
        <p>Local forecast: warm celsius weather ahead</p>
        <p>Markets closed early</p>
      </div>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            # CSS filter: only look inside the weather div
            'include_filters': 'div.weather',
            # Then keep only celsius lines from that section
            'extract_lines_containing': 'celsius',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)

    # Only the celsius line from the weather div should survive both filters
    assert b'celsius' in res.data
    # Other weather lines excluded by extract_lines_containing
    assert b'Humidity' not in res.data
    assert b'Wind' not in res.data
    # News div content excluded entirely by CSS filter (even though it contains "celsius")
    assert b'Markets' not in res.data
    assert b'forecast' not in res.data

    delete_all_watches(client)


# Re issue #4138: ignore_text must take effect BEFORE extract_text regex, otherwise the
# regex transforms line content (e.g. "v.1.2.1" -> "1.2.1") and ignore_text patterns
# like "v"/"rc" can no longer match — causing changes to ignored lines to incorrectly
# trigger change-detection.
def test_ignore_text_applied_before_extract_text_regex(client, live_server, measure_memory_usage, datastore_path):
    initial_data = """<html><body>
      <p>0.8.9</p>
      <p>v.1.2.1</p>
      <p>rc-1.0.0</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(initial_data)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'paused': True})

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
            'ignore_text': 'v\r\nrc',
            'extract_text': r'/(\d+\.\d+\.\d+)/',
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Bump only the IGNORED lines — these should not move the checksum
    changed_data = """<html><body>
      <p>0.8.9</p>
      <p>v.1.3.0</p>
      <p>rc-2.0.0</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(changed_data)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data, \
        "Changing only ignored lines should not trigger a change even when extract_text regex is set"

    client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    time.sleep(1)

    # Now bump the non-ignored line — this SHOULD trigger
    triggered_data = """<html><body>
      <p>0.9.0</p>
      <p>v.1.3.0</p>
      <p>rc-2.0.0</p>
    </body></html>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(triggered_data)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' in res.data, \
        "Changing a non-ignored line should still trigger a change"

    delete_all_watches(client)
