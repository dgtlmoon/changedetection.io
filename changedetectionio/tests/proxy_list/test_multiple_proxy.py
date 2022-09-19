#!/usr/bin/python3

import time
from flask import url_for
from ..util import live_server_setup

def test_preferred_proxy(client, live_server):
    time.sleep(1)
    live_server_setup(live_server)
    time.sleep(1)
    url = "http://chosen.changedetection.io"

    res = client.post(
        url_for("import_page"),
        # Because a URL wont show in squid/proxy logs due it being SSLed
        # Use plain HTTP or a specific domain-name here
        data={"urls": url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    time.sleep(2)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
                "css_filter": "",
                "fetch_backend": "html_requests",
                "headers": "",
                "proxy": "proxy-two",
                "tag": "",
                "url": url,
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(2)
    # Now the request should appear in the second-squid logs
