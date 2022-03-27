#!/usr/bin/python3

import time

from changedetectionio import store
from flask import url_for

from ..html_tools import *
from .util import live_server_setup


def test_setup(live_server):
    live_server_setup(live_server)


def set_original_response():
    test_return_data = """<html>
    <header>
    <h2>Header</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A</a></li>
      <li><a href="#">B</a></li>
      <li><a href="#">C</a></li>
    </ul>
    </nav>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
    <div id="changetext">Some text that will change</div>
     </body>
    <footer>
    <p>Footer</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_response():
    test_return_data = """<html>
    <header>
    <h2>Header changed</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A changed</a></li>
      <li><a href="#">B</a></li>
      <li><a href="#">C</a></li>
    </ul>
    </nav>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
    <div id="changetext">Some text that changes</div>
     </body>
    <footer>
    <p>Footer changed</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_share_filters_across_tags(client, live_server):
    sleep_time_for_fetch_thread = 3

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URLs to the import page
    test_url = url_for("test_endpoint", _external=True)
    # Add tags - the settings will be set for the first instance and should be copied to
    # the third if everything works correctly
    tags = [" one,two,three", " one,two", " one,two,three"]
    test_urls = "\n".join([test_url + x for x in tags])

    res = client.post(
        url_for("import_page"), data={"urls": test_urls}, follow_redirects=True
    )
    assert b"3 Imported" in res.data

    # Goto the edit page, add the filter data
    # Not sure why \r needs to be added - absent of the #changetext this is not necessary
    subtractive_selectors_data = "header\r\nfooter\r\nnav\r\n#changetext"
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "subtractive_selectors": subtractive_selectors_data,
            "url": test_url,
            "tag": "one,two,three",  # the first watch we added is supposed to have these tags
            "headers": "",
            "fetch_backend": "html_requests",
            "share_filters_across_tags": True,
        },
        follow_redirects=True,
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(subtractive_selectors_data.encode("utf-8")) in res.data

    # Check the settings also persist in the last watch
    res = client.get(
        url_for("edit_page", uuid="last"),
    )
    assert bytes(subtractive_selectors_data.encode("utf-8")) in res.data

    # Trigger a check
    res = client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # No change yet - first check
    res = client.get(url_for("index"))
    assert b"unviewed" not in res.data
    #  Make a change to header/footer/nav
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # There should be exactly one unviewed change, as changes should be removed for the
    # first and last watch because of the propagated removal
    res = client.get(url_for("index"))
    assert res.data.count(b"unviewed") == 1
