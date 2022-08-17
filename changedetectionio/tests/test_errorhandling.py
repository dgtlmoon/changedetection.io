#!/usr/bin/python3

import time

from flask import url_for
from . util import live_server_setup

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)


def _runner_test_http_errors(client, live_server, http_code, expected_text):

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("Now you going to get a {} error code\n".format(http_code))


    # Add our URL to the import page
    test_url = url_for('test_endpoint',
                       status_code=http_code,
                       _external=True)

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(2)

    res = client.get(url_for("index"))
    # no change
    assert b'unviewed' not in res.data
    assert bytes(expected_text.encode('utf-8')) in res.data


    # Error viewing tabs should appear
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'Error Text' in res.data

    # 'Error Screenshot' only when in playwright mode
    #assert b'Error Screenshot' in res.data


    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_http_error_handler(client, live_server):
    _runner_test_http_errors(client, live_server, 403, 'Access denied')
    _runner_test_http_errors(client, live_server, 404, 'Page not found')
    _runner_test_http_errors(client, live_server, 500, '(Internal server Error) received')
    _runner_test_http_errors(client, live_server, 400, 'Error - Request returned a HTTP error code 400')

# Just to be sure error text is properly handled
def test_DNS_errors(client, live_server):
    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": "https://errorfuldomainthatnevereallyexists12356.com"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    time.sleep(3)

    res = client.get(url_for("index"))
    assert b'Name or service not known' in res.data
    # Should always record that we tried
    assert bytes("just now".encode('utf-8')) in res.data

