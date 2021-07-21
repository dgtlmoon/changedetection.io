import json
import time
from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup

# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_headers_in_request(client, live_server):
    live_server_setup(live_server)

    # Add our URL to the import page
    test_url = url_for('test_headers', _external=True)

    # Add the test URL twice, we will check
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data


    # Add some headers to a request
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
              "url": test_url,
              "tag": "",
              "headers": "xxx:ooo\ncool:yeah\r\n",
              "trigger_check": "n"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data


    # Give the thread time to pick up the first version
    time.sleep(5)

    # The service should echo back the request headers
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    # Flask will convert the header key to uppercase
    assert b"Xxx:ooo" in res.data
    assert b"Cool:yeah" in res.data

    time.sleep(5)

    # Re #137 -  Examine the JSON index file, it should have only one set of headers entered
    watches_with_headers = 0
    with open('test-datastore/url-watches.json') as f:
        app_struct = json.load(f)
        for uuid in app_struct['watching']:
            if (len(app_struct['watching'][uuid]['headers'])):
                watches_with_headers += 1

    # Should be only one with headers set
    assert watches_with_headers==1







