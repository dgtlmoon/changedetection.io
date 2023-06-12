#!/usr/bin/python3

import time
from flask import url_for
from .util import live_server_setup, wait_for_all_checks

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

    res = client.get(
        url_for("tags.form_tag_edit", uuid="first")
    )
    assert b"#only-this" in res.data
    assert b"#not-this" in res.data

    # Tag should be setup and ready, now add a watch

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url + " test-tag, extra-import-tag"},
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

    time.sleep(1)
    wait_for_all_checks(client)

    res = client.get(url_for("index"))
    assert b'Warning, no filters were found' not in res.data

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'Should be only this' in res.data
    assert b'And never this' not in res.data

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
    assert res.data.count(b'test-tag') == 1

