#!/usr/bin/env python3
# coding=utf-8

import time
from flask import url_for, escape
from . util import live_server_setup, wait_for_all_checks
import pytest
jq_support = True

try:
    import jq
except ModuleNotFoundError:
    jq_support = False



def test_unittest_inline_html_extract():
    # So lets pretend that the JSON we want is inside some HTML
    content="""
    <html>
    
    food and stuff and more
    <script>
    alert('nothing really good here');
    </script>
    
    <script type="application/ld+json">
  xx {"@context":"http://schema.org","@type":"Product","name":"Nan Optipro Stage 1 Baby Formula  800g","description":"During the first year of life, nutrition is critical for your baby. NAN OPTIPRO 1 is tailored to ensure your formula fed infant receives balanced, high quality nutrition.<br />Starter infant formula. The age optimised protein source (whey dominant) is from cow’s milk.<br />Backed by more than 150 years of Nestlé expertise.<br />For hygiene and convenience, it is available in an innovative packaging format with a separate storage area for the scoop, and a semi-transparent window which allows you to see how much powder is left in the can without having to open it.","image":"https://cdn0.woolworths.media/content/wowproductimages/large/155536.jpg","brand":{"@context":"http://schema.org","@type":"Organization","name":"Nan"},"gtin13":"7613287517388","offers":{"@context":"http://schema.org","@type":"Offer","potentialAction":{"@context":"http://schema.org","@type":"BuyAction"},"availability":"http://schema.org/InStock","itemCondition":"http://schema.org/NewCondition","price":23.5,"priceCurrency":"AUD"},"review":[],"sku":"155536"}
</script>
<body>
and it can also be repeated
<script type="application/ld+json">
  {"@context":"http://schema.org","@type":"Product","name":"Nan Optipro Stage 1 Baby Formula  800g","description":"During the first year of life, nutrition is critical for your baby. NAN OPTIPRO 1 is tailored to ensure your formula fed infant receives balanced, high quality nutrition.<br />Starter infant formula. The age optimised protein source (whey dominant) is from cow’s milk.<br />Backed by more than 150 years of Nestlé expertise.<br />For hygiene and convenience, it is available in an innovative packaging format with a separate storage area for the scoop, and a semi-transparent window which allows you to see how much powder is left in the can without having to open it.","image":"https://cdn0.woolworths.media/content/wowproductimages/large/155536.jpg","brand":{"@context":"http://schema.org","@type":"Organization","name":"Nan"},"gtin13":"7613287517388","offers":{"@context":"http://schema.org","@type":"Offer","potentialAction":{"@context":"http://schema.org","@type":"BuyAction"},"availability":"http://schema.org/InStock","itemCondition":"http://schema.org/NewCondition","price":23.5,"priceCurrency":"AUD"},"review":[],"sku":"155536"}
</script>
<h4>ok</h4>
</body>
</html>

    """
    from .. import html_tools

    # See that we can find the second <script> one, which is not broken, and matches our filter
    text = html_tools.extract_json_as_string(content, "json:$.offers.priceCurrency")
    assert text == '"AUD"'

    text = html_tools.extract_json_as_string('{"id":5}', "json:$.id")
    assert text == "5"

    # also check for jq
    if jq_support:
        text = html_tools.extract_json_as_string(content, "jq:.offers.priceCurrency")
        assert text == '"AUD"'

        text = html_tools.extract_json_as_string('{"id":5}', "jq:.id")
        assert text == "5"

        text = html_tools.extract_json_as_string(content, "jqraw:.offers.priceCurrency")
        assert text == "AUD"

        text = html_tools.extract_json_as_string('{"id":5}', "jqraw:.id")
        assert text == "5"


    # When nothing at all is found, it should throw JSONNOTFound
    # Which is caught and shown to the user in the watch-overview table
    with pytest.raises(html_tools.JSONNotFound) as e_info:
        html_tools.extract_json_as_string('COMPLETE GIBBERISH, NO JSON!', "json:$.id")

    if jq_support:
        with pytest.raises(html_tools.JSONNotFound) as e_info:
            html_tools.extract_json_as_string('COMPLETE GIBBERISH, NO JSON!', "jq:.id")

        with pytest.raises(html_tools.JSONNotFound) as e_info:
            html_tools.extract_json_as_string('COMPLETE GIBBERISH, NO JSON!', "jqraw:.id")


def test_unittest_inline_extract_body():
    content = """
    <html>
        <head></head>
        <body>
            <pre style="word-wrap: break-word; white-space: pre-wrap;">
                {"testKey": 42}
            </pre>
        </body>
    </html>
    """
    from .. import html_tools

    # See that we can find the second <script> one, which is not broken, and matches our filter
    text = html_tools.extract_json_as_string(content, "json:$.testKey")
    assert text == '42'

def set_original_ext_response():
    data = """
        [
        {
            "isPriceLowered": false,
            "status": "ForSale",
            "statusOrig": "for sale"
        },
        {
            "_id": "5e7b3e1fb3262d306323ff1e",
            "listingsType": "consumer",
            "status": "ForSale",
            "statusOrig": "for sale"
        }
    ]
        """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(data)
    return None

def set_modified_ext_response():
    data = """
    [
    {
        "isPriceLowered": false,
        "status": "Sold",
        "statusOrig": "sold"
    },
    {
        "_id": "5e7b3e1fb3262d306323ff1e",
        "listingsType": "consumer",
        "isPriceLowered": false,
        "status": "Sold"
    }
]
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(data)
    return None

def set_original_response():
    test_return_data = """
    {
      "employees": [
        {
          "id": 1,
          "name": "Pankaj",
          "salary": "10000"
        },
        {
          "name": "David",
          "salary": "5000",
          "id": 2
        }
      ],
      "boss": {
        "name": "Fat guy"
      },
      "available": true
    }
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None


def set_json_response_with_html():
    test_return_data = """
    {
      "test": [
        {
          "html": "<b>"
        }
      ]
    }
    """
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_modified_response():
    test_return_data = """
    {
      "employees": [
        {
          "id": 1,
          "name": "Pankaj",
          "salary": "10000"
        },
        {
          "name": "David",
          "salary": "5000",
          "id": 2
        }
      ],
      "boss": {
        "name": "Örnsköldsvik"
      },
      "available": false
    }
        """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None

def test_check_json_without_filter(client, live_server, measure_memory_usage):
    # Request a JSON document from a application/json source containing HTML
    # and be sure it doesn't get chewed up by instriptis
    set_json_response_with_html()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    # Should still see '"html": "<b>"'
    assert b'&#34;html&#34;: &#34;&lt;b&gt;&#34;' in res.data
    assert res.data.count(b'{') >= 2

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def check_json_filter(json_filter, client, live_server):
    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": json_filter,
              "url": test_url,
              "tags": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
    )
    assert bytes(escape(json_filter).encode('utf-8')) in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should have 'unviewed' still
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    # Should not see this, because its not in the JSONPath we entered
    res = client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))

    # But the change should be there, tho its hard to test the change was detected because it will show old and new versions
    # And #462 - check we see the proper utf-8 string there
    assert "Örnsköldsvik".encode('utf-8') in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_check_jsonpath_filter(client, live_server, measure_memory_usage):
    check_json_filter('json:boss.name', client, live_server)

def test_check_jq_filter(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_filter('jq:.boss.name', client, live_server)

def test_check_jqraw_filter(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_filter('jqraw:.boss.name', client, live_server)

def check_json_filter_bool_val(json_filter, client, live_server):
    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    test_url = url_for('test_endpoint', content_type="application/json", _external=True)

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": json_filter,
              "url": test_url,
              "tags": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))
    # But the change should be there, tho its hard to test the change was detected because it will show old and new versions
    assert b'false' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_check_jsonpath_filter_bool_val(client, live_server, measure_memory_usage):
    check_json_filter_bool_val("json:$['available']", client, live_server)

def test_check_jq_filter_bool_val(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_filter_bool_val("jq:.available", client, live_server)

def test_check_jqraw_filter_bool_val(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_filter_bool_val("jq:.available", client, live_server)

# Re #265 - Extended JSON selector test
# Stuff to consider here
# - Selector should be allowed to return empty when it doesnt match (people might wait for some condition)
# - The 'diff' tab could show the old and new content
# - Form should let us enter a selector that doesnt (yet) match anything
def check_json_ext_filter(json_filter, client, live_server):
    set_original_ext_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": json_filter,
              "url": test_url,
              "tags": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("ui.ui_edit.edit_page", uuid="first"),
    )
    assert bytes(escape(json_filter).encode('utf-8')) in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)
    #  Make a change
    set_modified_ext_response()

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # It should have 'unviewed'
    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("ui.ui_views.diff_history_page", uuid="first"))

    # We should never see 'ForSale' because we are selecting on 'Sold' in the rule,
    # But we should know it triggered ('unviewed' assert above)
    assert b'ForSale' not in res.data
    assert b'Sold' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_ignore_json_order(client, live_server, measure_memory_usage):
    # A change in order shouldn't trigger a notification

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write('{"hello" : 123, "world": 123}')


    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write('{"world" : 123, "hello": 123}')

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' not in res.data

    # Just to be sure it still works
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write('{"world" : 123, "hello": 124}')

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_correct_header_detect(client, live_server, measure_memory_usage):
    # Like in https://github.com/dgtlmoon/changedetection.io/pull/1593
    # Specify extra html that JSON is sometimes wrapped in - when using SockpuppetBrowser / Puppeteer / Playwrightetc
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write('<html><body>{"hello" : 123, "world": 123}')

    # Add our URL to the import page
    # Check weird casing is cleaned up and detected also
    test_url = url_for('test_endpoint', content_type="aPPlication/JSon", uppercase_headers=True, _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))

    # Fixed in #1593
    assert b'No parsable JSON found in this document' not in res.data

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'&#34;hello&#34;: 123,' in res.data
    assert b'&#34;world&#34;: 123' in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_check_jsonpath_ext_filter(client, live_server, measure_memory_usage):
    check_json_ext_filter('json:$[?(@.status==Sold)]', client, live_server)

def test_check_jq_ext_filter(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_ext_filter('jq:.[] | select(.status | contains("Sold"))', client, live_server)

def test_check_jqraw_ext_filter(client, live_server, measure_memory_usage):
    if jq_support:
        check_json_ext_filter('jq:.[] | select(.status | contains("Sold"))', client, live_server)

def test_jsonpath_BOM_utf8(client, live_server, measure_memory_usage):
    from .. import html_tools

    # JSON string with BOM and correct double-quoted keys
    json_str = '\ufeff{"name": "José", "emoji": "😊", "language": "中文", "greeting": "Привет"}'

    # See that we can find the second <script> one, which is not broken, and matches our filter
    text = html_tools.extract_json_as_string(json_str, "json:$.name")
    assert text == '"José"'

    
