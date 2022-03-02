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
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
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
    <h2>Header</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">AAA</a></li>
      <li><a href="#">B</a></li>
      <li><a href="#">C</a></li>
    </ul>
    </nav>
       <body>
     Some initial text</br>
     <p>which has this one new line</p>
     </br>
     So let's see what happens.  </br>
     </body>
    <footer>
    <p>Changed footer</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_body_filter_output():
    from changedetectionio import fetch_site_status
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
     Some initial text</br>
     <p>across multiple lines</p>
     </body>
    <footer>
    <p>Footer</p>
    </footer>
     </html>
    """
    html_blob = ignore_tags(html_content=content)
    text = get_text(html_blob)
    assert (
        text
        == """Some initial text

across multiple lines
"""
    )


def test_check_markup_css_filter_restriction(client, live_server):
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

    # Goto the edit page, add the body filter
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "filter_body": True,
            "url": test_url,
            "tag": "",
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
    # Need to have value="y"
    filter_body_html = (
        '<input checked id="filter_body" name="filter_body" type="checkbox" value="y">'
    )
    assert bytes(filter_body_html.encode("utf-8")) in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    #  Make a change to header/footer/nav
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # It should have 'unviewed' still, as we removed footer
    res = client.get(url_for("index"))
    assert b"unviewed" in res.data
