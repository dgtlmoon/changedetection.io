#!/usr/bin/env python3

from flask import url_for
from changedetectionio.tests.util import live_server_setup, wait_for_all_checks, extract_UUID_from_client


def set_response():

    data = """<html>
       <body>Awesome, you made it<br>
yeah the socks request worked<br>
something to ignore<br>
something to trigger<br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(data)

def test_content_filter_live_preview(client, live_server, measure_memory_usage):
   #  live_server_setup(live_server) # Setup on conftest per function
    set_response()

    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True
    )
    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "something to ignore",
            "trigger_text": "something to trigger",
            "url": test_url,
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    # The endpoint is a POST and accepts the form values to override the watch preview
    import json

    # DEFAULT OUTPUT WITHOUT ANYTHING UPDATED/CHANGED - SHOULD SEE THE WATCH DEFAULTS
    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid)
    )
    default_return = json.loads(res.data.decode('utf-8'))
    assert default_return.get('after_filter')
    assert default_return.get('before_filter')
    assert default_return.get('ignore_line_numbers') == [3] # "something to ignore" line 3
    assert default_return.get('trigger_line_numbers') == [4] # "something to trigger" line 4

    # SEND AN UPDATE AND WE SHOULD SEE THE OUTPUT CHANGE SO WE KNOW TO HIGHLIGHT NEW STUFF
    res = client.post(
        url_for("ui.ui_edit.watch_get_preview_rendered", uuid=uuid),
        data={
            "include_filters": "",
            "fetch_backend": 'html_requests',
            "ignore_text": "sOckS", # Also be sure case insensitive works
            "trigger_text": "AweSOme",
            "url": test_url,
        },
    )
    reply = json.loads(res.data.decode('utf-8'))
    assert reply.get('after_filter')
    assert reply.get('before_filter')
    assert reply.get('ignore_line_numbers') == [2]  # Ignored - "socks" on line 2
    assert reply.get('trigger_line_numbers') == [1]  # Triggers "Awesome" in line 1

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data
