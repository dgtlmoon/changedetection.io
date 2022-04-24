#!/usr/bin/python3
# coding=utf-8

import time
from flask import url_for
from . util import live_server_setup
import pytest


def test_setup(live_server):
    live_server_setup(live_server)

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
    text = html_tools.extract_json_as_string(content, "$.offers.price")
    assert text == "23.5"

    text = html_tools.extract_json_as_string('{"id":5}', "$.id")
    assert text == "5"

    # When nothing at all is found, it should throw JSONNOTFound
    # Which is caught and shown to the user in the watch-overview table
    with pytest.raises(html_tools.JSONNotFound) as e_info:
        html_tools.extract_json_as_string('COMPLETE GIBBERISH, NO JSON!', "$.id")

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


def set_response_with_html():
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

def test_check_json_without_filter(client, live_server):
    # Request a JSON document from a application/json source containing HTML
    # and be sure it doesn't get chewed up by instriptis
    set_response_with_html()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'&#34;&lt;b&gt;' in res.data
    assert res.data.count(b'{\n') >= 2


def test_check_json_filter(client, live_server):
    json_filter = 'json:boss.name'

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": json_filter,
              "url": test_url,
              "tag": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(json_filter.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(4)

    # It should have 'unviewed' still
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    # Should not see this, because its not in the JSONPath we entered
    res = client.get(url_for("diff_history_page", uuid="first"))

    # But the change should be there, tho its hard to test the change was detected because it will show old and new versions
    # And #462 - check we see the proper utf-8 string there
    assert "Örnsköldsvik".encode('utf-8') in res.data


def test_check_json_filter_bool_val(client, live_server):
    json_filter = "json:$['available']"

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    test_url = url_for('test_endpoint', content_type="application/json", _external=True)

    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    time.sleep(3)
    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": json_filter,
              "url": test_url,
              "tag": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    time.sleep(3)

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)
    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(3)

    res = client.get(url_for("diff_history_page", uuid="first"))
    # But the change should be there, tho its hard to test the change was detected because it will show old and new versions
    assert b'false' in res.data

# Re #265 - Extended JSON selector test
# Stuff to consider here
# - Selector should be allowed to return empty when it doesnt match (people might wait for some condition)
# - The 'diff' tab could show the old and new content
# - Form should let us enter a selector that doesnt (yet) match anything
def test_check_json_ext_filter(client, live_server):
    json_filter = 'json:$[?(@.status==Sold)]'

    set_original_ext_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type="application/json", _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": json_filter,
              "url": test_url,
              "tag": "",
              "headers": "",
              "fetch_backend": "html_requests"
              },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(json_filter.encode('utf-8')) in res.data

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(3)
    #  Make a change
    set_modified_ext_response()

    # Trigger a check
    client.get(url_for("api_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(4)

    # It should have 'unviewed'
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("diff_history_page", uuid="first"))

    # We should never see 'ForSale' because we are selecting on 'Sold' in the rule,
    # But we should know it triggered ('unviewed' assert above)
    assert b'ForSale' not in res.data
    assert b'Sold' in res.data

