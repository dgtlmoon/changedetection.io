from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup
import time

def test_setup(live_server):
    live_server_setup(live_server)

def test_basic_search(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    urls = ['https://localhost:12300?first-result=1',
            'https://localhost:5000?second-result=1'
            ]
    res = client.post(
        url_for("import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )

    assert b"2 Imported" in res.data

    # By URL
    res = client.get(url_for("index") + "?q=first-res")
    assert urls[0].encode('utf-8') in res.data
    assert urls[1].encode('utf-8') not in res.data

    # By Title

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"title": "xxx-title", "url": urls[0], "tags": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("index") + "?q=xxx-title")
    assert urls[0].encode('utf-8') in res.data
    assert urls[1].encode('utf-8') not in res.data


def test_search_in_tag_limit(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    urls = ['https://localhost:12300?first-result=1 tag-one',
            'https://localhost:5000?second-result=1 tag-two'
            ]
    res = client.post(
        url_for("import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )

    assert b"2 Imported" in res.data

    # By URL

    res = client.get(url_for("index") + "?q=first-res")
    # Split because of the import tag separation
    assert urls[0].split(' ')[0].encode('utf-8') in res.data, urls[0].encode('utf-8')
    assert urls[1].split(' ')[0].encode('utf-8') not in res.data, urls[0].encode('utf-8')

    # By Title
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"title": "xxx-title", "url": urls[0].split(' ')[0], "tags": urls[0].split(' ')[1], "headers": "",
              'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("index") + "?q=xxx-title")
    assert urls[0].split(' ')[0].encode('utf-8') in res.data, urls[0].encode('utf-8')
    assert urls[1].split(' ')[0].encode('utf-8') not in res.data, urls[0].encode('utf-8')

