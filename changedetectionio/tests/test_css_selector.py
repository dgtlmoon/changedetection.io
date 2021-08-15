#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
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
     Some initial text</br>
     <p>which has this one new line</p>
     </br>
     So let's see what happens.  </br>
     <div id="sametext">Some text thats the same</div>
     <div id="changetext">Some text that changes</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None


# Test that the CSS extraction works how we expect, important here is the right placing of new lines \n's
def test_css_filter_output():
    from changedetectionio import fetch_site_status
    from inscriptis import get_text

    # Check text with sub-parts renders correctly
    content = """<html> <body><div id="thingthing" >  Some really <b>bold</b> text  </div> </body> </html>"""
    html_blob = css_filter(css_filter="#thingthing", html_content=content)
    text = get_text(html_blob)
    assert text == "  Some really bold text"

    content = """<html> <body>
    <p>foo bar blah</p>
    <div class="parts">Block A</div> <div class="parts">Block B</div></body> 
    </html>
"""
    html_blob = css_filter(css_filter=".parts", html_content=content)
    text = get_text(html_blob)

    # Divs are converted to 4 whitespaces by inscriptis
    assert text == "    Block A\n    Block B"


# Tests the whole stack works with the CSS Filter
def test_check_markup_css_filter_restriction(client, live_server):
    sleep_time_for_fetch_thread = 3

    css_filter = "#sametext"

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

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": css_filter, "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(css_filter.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should have 'unviewed' still
    # Because it should be looking at only that 'sametext' id
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
