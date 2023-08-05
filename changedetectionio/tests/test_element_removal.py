#!/usr/bin/python3

import time

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
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
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
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
    <div id="changetext">Some text that changes</div>
     </body>
    <footer>
    <p>Footer changed</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_element_removal_output():
    from inscriptis import get_text

    # Check text with sub-parts renders correctly
    content = """<html>
    <header>
    <h2>Header</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A</a></li>
    </ul>
    </nav>
       <body>
     Some initial text<br>
     <p>across multiple lines</p>
     <div id="changetext">Some text that changes</div>
     </body>
    <footer>
    <p>Footer</p>
    </footer>
     </html>
    """
    html_blob = element_removal(
        ["header", "footer", "nav", "#changetext"], html_content=content
    )
    text = get_text(html_blob)
    assert (
        text
        == """Some initial text

across multiple lines
"""
    )


def test_element_removal_full(client, live_server):
    sleep_time_for_fetch_thread = 3

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for("test_endpoint", _external=True)
    res = client.post(
        url_for("import_page"), data={"urls": test_url}, follow_redirects=True
    )
    assert b"1 Imported" in res.data
    time.sleep(1)
    # Goto the edit page, add the filter data
    # Not sure why \r needs to be added - absent of the #changetext this is not necessary
    subtractive_selectors_data = "header\r\nfooter\r\nnav\r\n#changetext"
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "subtractive_selectors": subtractive_selectors_data,
            "url": test_url,
            "tags": "",
            "headers": "",
            "fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(subtractive_selectors_data.encode("utf-8")) in res.data

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # so that we set the state to 'unviewed' after all the edits
    client.get(url_for("diff_history_page", uuid="first"))

    #  Make a change to header/footer/nav
    set_modified_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # There should not be an unviewed change, as changes should be removed
    res = client.get(url_for("index"))
    assert b"unviewed" not in res.data
