import time
from flask import url_for
from urllib.request import urlopen
from . util import set_original_response, set_modified_response, live_server_setup


def test_check_watch_field_storage(client, live_server):
    set_original_response()
    live_server_setup(live_server)

    test_url = "http://somerandomsitewewatch.com"

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data


    res = client.post(
        url_for("edit_page", uuid="first"),
        data={ "notification_urls": "http://myapi.com",
               "minutes_between_check": 126,
               "css_filter" : ".fooclass",
               "title" : "My title",
               "ignore_text" : "ignore this",
               "url": test_url,
               "tag": "woohoo",
               "headers": "curl:foo",

               },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(
        url_for("edit_page", uuid="first"),
        follow_redirects=True
    )

    assert b"http://myapi.com" in res.data
    assert b"126" in res.data
    assert b".fooclass" in res.data
    assert b"My title" in res.data
    assert b"ignore this" in res.data
    assert b"http://somerandomsitewewatch.com" in res.data
    assert b"woohoo" in res.data
    assert b"curl: foo" in res.data



