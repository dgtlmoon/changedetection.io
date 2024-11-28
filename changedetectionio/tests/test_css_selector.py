#!/usr/bin/env python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div id="changetext">Some text that will change</div>
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
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     <div id="sametext">Some text thats the same</div>
     <div id="changetext">Some text that changes</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None


# Test that the CSS extraction works how we expect, important here is the right placing of new lines \n's
def test_include_filters_output():
    from inscriptis import get_text

    # Check text with sub-parts renders correctly
    content = """<html> <body><div id="thingthing" >  Some really <b>bold</b> text  </div> </body> </html>"""
    html_blob = include_filters(include_filters="#thingthing", html_content=content)
    text = get_text(html_blob)
    assert text == "  Some really bold text"

    content = """<html> <body>
    <p>foo bar blah</p>
    <DIV class="parts">Block A</DiV> <div class="parts">Block B</DIV></body> 
    </html>
"""

    # in xPath this would be //*[@class='parts']
    html_blob = include_filters(include_filters=".parts", html_content=content)
    text = get_text(html_blob)

    # Divs are converted to 4 whitespaces by inscriptis
    assert text == "    Block A\n    Block B"


# Tests the whole stack works with the CSS Filter
def test_check_markup_include_filters_restriction(client, live_server, measure_memory_usage):
    sleep_time_for_fetch_thread = 3

    include_filters = "#sametext"

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"include_filters": include_filters, "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(1)
    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(include_filters.encode('utf-8')) in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should have 'unviewed' still
    # Because it should be looking at only that 'sametext' id
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data


# Tests the whole stack works with the CSS Filter
def test_check_multiple_filters(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    include_filters = "#blob-a\r\nxpath://*[contains(@id,'blob-b')]"

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""<html><body>
     <div id="blob-a">Blob A</div>
     <div id="blob-b">Blob B</div>
     <div id="blob-c">Blob C</div>
     </body>
     </html>
    """)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"include_filters": include_filters,
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Only the two blobs should be here
    assert b"Blob A" in res.data # CSS was ok
    assert b"Blob B" in res.data # xPath was ok
    assert b"Blob C" not in res.data # Should not be included

# The filter exists, but did not contain anything useful
# Mainly used when the filter contains just an IMG, this can happen when someone selects an image in the visual-selector
# Tests fetcher can throw a "ReplyWithContentButNoText" exception after applying filter and extracting text
def test_filter_is_empty_help_suggestion(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    include_filters = "#blob-a"

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""<html><body>
         <div id="blob-a">
           <img src="something.jpg">
         </div>
         </body>
         </html>
        """)


    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"include_filters": include_filters,
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)


    res = client.get(
        url_for("index"),
        follow_redirects=True
    )

    assert b'empty result or contain only an image' in res.data


    ### Just an empty selector, no image

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("""<html><body>
         <div id="blob-a">
           <!-- doo doo -->
         </div>
         </body>
         </html>
        """)

    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(
        url_for("index"),
        follow_redirects=True
    )

    assert b'empty result or contain only an image' not in res.data
    assert b'but contained no usable text' in res.data
