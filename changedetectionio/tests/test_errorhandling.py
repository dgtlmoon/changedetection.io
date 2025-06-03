#!/usr/bin/env python3

import time

from flask import url_for
from .util import live_server_setup, wait_for_all_checks




def _runner_test_http_errors(client, live_server, http_code, expected_text):

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("Now you going to get a {} error code\n".format(http_code))


    # Add our URL to the import page
    test_url = url_for('test_endpoint',
                       status_code=http_code,
                       _external=True)

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    # no change
    assert b'unviewed' not in res.data
    assert bytes(expected_text.encode('utf-8')) in res.data


    # Error viewing tabs should appear
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'Error Text' in res.data

    # 'Error Screenshot' only when in playwright mode
    #assert b'Error Screenshot' in res.data


    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_http_error_handler(client, live_server, measure_memory_usage):
    _runner_test_http_errors(client, live_server, 403, 'Access denied')
    _runner_test_http_errors(client, live_server, 404, 'Page not found')
    _runner_test_http_errors(client, live_server, 500, '(Internal server error) received')
    _runner_test_http_errors(client, live_server, 400, 'Error - Request returned a HTTP error code 400')
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# Just to be sure error text is properly handled
def test_DNS_errors(client, live_server, measure_memory_usage):
    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "https://errorfuldomainthatnevereallyexists12356.com"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    found_name_resolution_error = (
        b"No address found" in res.data or
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data
    )
    assert found_name_resolution_error
    # Should always record that we tried
    assert bytes("just now".encode('utf-8')) in res.data
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# Re 1513
def test_low_level_errors_clear_correctly(client, live_server, measure_memory_usage):
    
    # Give the endpoint time to spin up
    time.sleep(1)

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("<html><body><div id=here>Hello world</div></body></html>")

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "https://dfkjasdkfjaidjfsdajfksdajfksdjfDOESNTEXIST.com"},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # We should see the DNS error
    res = client.get(url_for("watchlist.index"))
    found_name_resolution_error = (
        b"No address found" in res.data or
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data
    )
    assert found_name_resolution_error

    # Update with what should work
    client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": "html_requests"},
        follow_redirects=True
    )

    # Now the error should be gone
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    found_name_resolution_error = (
        b"No address found" in res.data or
        b"Name or service not known" in res.data or
        b"nodename nor servname provided" in res.data or
        b"Temporary failure in name resolution" in res.data or
        b"Failed to establish a new connection" in res.data or
        b"Connection error occurred" in res.data
    )
    assert not found_name_resolution_error

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
