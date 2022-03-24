#!/usr/bin/python3
# coding=utf-8

import time
from flask import url_for
from .util import live_server_setup
import pytest


def test_setup(live_server):
    live_server_setup(live_server)


def set_html_response():
    test_return_data = """
<html><body><span class="nav_second_img_text">
                  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;铸大国重器，挺制造脊梁，致力能源未来，赋能美好生活。
                                  </span>
</body></html>
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None


# In the case the server does not issue a charset= or doesnt have content_type header set
def test_check_encoding_detection(client, live_server):
    set_html_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="text/html", _external=True)
    client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(2)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "铸大国重".encode('utf-8') in res.data
    # Should not see the failed encoding
    assert b'\xc2\xa7' not in res.data


# In the case the server does not issue a charset= or doesnt have content_type header set
def test_check_encoding_detection_missing_content_type_header(client, live_server):
    set_html_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(2)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should see the proper string
    assert "铸大国重".encode('utf-8') in res.data
    # Should not see the failed encoding
    assert b'\xc2\xa7' not in res.data
