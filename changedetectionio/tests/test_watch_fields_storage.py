import time
from flask import url_for
from urllib.request import urlopen
from . util import set_original_response, set_modified_response, live_server_setup


def test_check_watch_field_storage(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)

   #  live_server_setup(live_server) # Setup on conftest per function

    test_url = "http://somerandomsitewewatch.com"

    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)


    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={ "notification_urls": "json://127.0.0.1:30000\r\njson://128.0.0.1\r\n",
               "time_between_check-minutes": 126,
               "include_filters" : ".fooclass",
               "title" : "My title",
               "ignore_text" : "ignore this",
               "url": test_url,
               "tags": "woohoo",
               "headers": "curl:foo",
               'fetch_backend': "html_requests",
               "time_between_check_use_default": "y"
               },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        follow_redirects=True
    )
    # checks that we dont get an error when using blank lines in the field value
    assert not b"json://127.0.0.1\n\njson" in res.data
    assert not b"json://127.0.0.1\r\n\njson" in res.data
    assert not b"json://127.0.0.1\r\n\rjson" in res.data

    assert b"json://127.0.0.1" in res.data
    assert b"json://128.0.0.1" in res.data

    assert b"126" in res.data
    assert b".fooclass" in res.data
    assert b"My title" in res.data
    assert b"ignore this" in res.data
    assert b"http://somerandomsitewewatch.com" in res.data
    assert b"woohoo" in res.data
    assert b"curl: foo" in res.data

