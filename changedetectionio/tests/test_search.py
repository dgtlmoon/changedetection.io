from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup
import re
import time



def test_basic_search(client, live_server, measure_memory_usage, datastore_path):
    

    urls = ['https://localhost:12300?first-result=1',
            'https://localhost:5000?second-result=1'
            ]
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )

    assert b"2 Imported" in res.data

    # By URL
    res = client.get(url_for("watchlist.index") + "?q=first-res")
    assert urls[0].encode('utf-8') in res.data
    assert urls[1].encode('utf-8') not in res.data

    # By Title

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"title": "xxx-title", "url": urls[0], "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("watchlist.index") + "?q=xxx-title")
    assert urls[0].encode('utf-8') in res.data
    assert urls[1].encode('utf-8') not in res.data


def test_search_in_tag_limit(client, live_server, measure_memory_usage, datastore_path):
    

    urls = ['https://localhost:12300?first-result=1 tag-one',
            'https://localhost:5000?second-result=1 tag-two'
            ]
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )

    assert b"2 Imported" in res.data

    # By URL

    res = client.get(url_for("watchlist.index") + "?q=first-res")
    # Split because of the import tag separation
    assert urls[0].split(' ')[0].encode('utf-8') in res.data, urls[0].encode('utf-8')
    assert urls[1].split(' ')[0].encode('utf-8') not in res.data, urls[0].encode('utf-8')

    # By Title
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"title": "xxx-title", "url": urls[0].split(' ')[0], "tags": urls[0].split(' ')[1], "headers": "",
              'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    res = client.get(url_for("watchlist.index") + "?q=xxx-title")
    assert urls[0].split(' ')[0].encode('utf-8') in res.data, urls[0].encode('utf-8')
    assert urls[1].split(' ')[0].encode('utf-8') not in res.data, urls[0].encode('utf-8')



def test_search_modal_tag_field_is_filterable(client, live_server, measure_memory_usage, datastore_path):
    # The modal carries the active tag as a hidden field so a search stays scoped to the
    # tag you were viewing. The field name has to be the one the watchlist filters on.
    urls = ['https://localhost:12300?first-result=1 tag-one',
            'https://localhost:5000?second-result=1 tag-two'
            ]
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(urls)},
        follow_redirects=True
    )
    assert b"2 Imported" in res.data

    res = client.get(url_for("watchlist.index") + "?tag=tag-one")
    form = re.search(rb'<form id="search-form".*?</form>', res.data, re.DOTALL)
    assert form, "search modal form not rendered"
    field = re.search(rb'<input name="([^"]+)" type="hidden" value="([^"]+)"', form.group(0))
    assert field, f"no populated hidden tag field in {form.group(0)}"
    name, value = field.group(1).decode(), field.group(2).decode()

    # 'localhost' matches both watches, so only the tag field can narrow it down
    res = client.get(url_for("watchlist.index") + f"?q=localhost&{name}={value}")
    assert urls[0].split(' ')[0].encode('utf-8') in res.data
    assert urls[1].split(' ')[0].encode('utf-8') not in res.data, f"'{name}' is not filtered on by the watchlist"
