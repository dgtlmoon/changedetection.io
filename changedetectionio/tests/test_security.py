from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup
import time

def test_setup(live_server):
    live_server_setup(live_server)

def test_file_access(client, live_server):

    res = client.post(
        url_for("import_page"),
        data={"urls": 'https://localhost'},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    # Attempt to add a body with a GET method
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
              "url": 'file:///etc/passwd',
              "tag": "",
              "method": "GET",
              "fetch_backend": "html_requests",
              "body": ""},
        follow_redirects=True
    )
    time.sleep(3)

    res = client.get(
        url_for("index", uuid="first"),
        follow_redirects=True
    )

    assert b'denied for security reasons' in res.data
