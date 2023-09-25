#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks


def test_preferred_proxy(client, live_server):
    live_server_setup(live_server)
    url = "http://chosen.changedetection.io"

    res = client.post(
        url_for("import_page"),
        # Because a URL wont show in squid/proxy logs due it being SSLed
        # Use plain HTTP or a specific domain-name here
        data={"urls": url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
                "include_filters": "",
                "fetch_backend": "html_requests",
                "headers": "",
                "proxy": "proxy-two",
                "tags": "",
                "url": url,
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    # Now the request should appear in the second-squid logs
