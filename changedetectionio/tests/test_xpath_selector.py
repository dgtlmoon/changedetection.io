#!/usr/bin/python3

import time
from flask import url_for
from . util import live_server_setup

from ..html_tools import *

def test_setup(live_server):
    live_server_setup(live_server)

def set_original_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_modified_response():
    test_return_data = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  THIS CHANGES AND SHOULDNT TRIGGER A CHANGE</br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some new text</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None

# Handle utf-8 charset replies https://github.com/dgtlmoon/changedetection.io/pull/613
def test_check_xpath_filter_utf8(client, live_server):
    filter='//item/*[self::description]'

    d='''<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:taxo="http://purl.org/rss/1.0/modules/taxonomy/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
	<channel>
		<title>rpilocator.com</title>
		<link>https://rpilocator.com</link>
		<description>Find Raspberry Pi Computers in Stock</description>
		<lastBuildDate>Thu, 19 May 2022 23:27:30 GMT</lastBuildDate>
		<image>
			<url>https://rpilocator.com/favicon.png</url>
			<title>rpilocator.com</title>
			<link>https://rpilocator.com/</link>
			<width>32</width>
			<height>32</height>
		</image>
		<item>
			<title>Stock Alert (UK): RPi CM4 - 1GB RAM, No MMC, No Wifi is In Stock at Pimoroni</title>
			<description>Stock Alert (UK): RPi CM4 - 1GB RAM, No MMC, No Wifi is In Stock at Pimoroni</description>
			<link>https://rpilocator.com?vendor=pimoroni&amp;utm_source=feed&amp;utm_medium=rss</link>
			<category>pimoroni</category>
			<category>UK</category>
			<category>CM4</category>
			<guid isPermaLink="false">F9FAB0D9-DF6F-40C8-8DEE5FC0646BB722</guid>
			<pubDate>Thu, 19 May 2022 14:32:32 GMT</pubDate>
		</item>
	</channel>
</rss>'''

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(d)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True, content_type="application/rss+xml;charset=UTF-8")
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    time.sleep(1)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": filter, "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(3)
    res = client.get(url_for("index"))
    assert b'Unicode strings with encoding declaration are not supported.' not in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


# Handle utf-8 charset replies https://github.com/dgtlmoon/changedetection.io/pull/613
def test_check_xpath_text_function_utf8(client, live_server):
    filter='//item/title/text()'

    d='''<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:taxo="http://purl.org/rss/1.0/modules/taxonomy/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
	<channel>
		<title>rpilocator.com</title>
		<link>https://rpilocator.com</link>
		<description>Find Raspberry Pi Computers in Stock</description>
		<lastBuildDate>Thu, 19 May 2022 23:27:30 GMT</lastBuildDate>
		<image>
			<url>https://rpilocator.com/favicon.png</url>
			<title>rpilocator.com</title>
			<link>https://rpilocator.com/</link>
			<width>32</width>
			<height>32</height>
		</image>
		<item>
			<title>Stock Alert (UK): RPi CM4</title>
			<foo>something else unrelated</foo>
		</item>
		<item>
			<title>Stock Alert (UK): Big monitor</title>
			<foo>something else unrelated</foo>
		</item>		
	</channel>
</rss>'''

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(d)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True, content_type="application/rss+xml;charset=UTF-8")
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    time.sleep(1)
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": filter, "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    time.sleep(3)
    res = client.get(url_for("index"))
    assert b'Unicode strings with encoding declaration are not supported.' not in res.data

    # The service should echo back the request headers
    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'<div class="">Stock Alert (UK): RPi CM4' in res.data
    assert b'<div class="">Stock Alert (UK): Big monitor' in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_check_markup_xpath_filter_restriction(client, live_server):
    sleep_time_for_fetch_thread = 3

    xpath_filter = "//*[contains(@class, 'sametext')]"

    set_original_response()

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": xpath_filter, "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    # view it/reset state back to viewed
    client.get(url_for("diff_history_page", uuid="first"), follow_redirects=True)

    #  Make a change
    set_modified_response()

    # Trigger a check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    time.sleep(sleep_time_for_fetch_thread)

    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


def test_xpath_validation(client, live_server):

    # Give the endpoint time to spin up
    time.sleep(1)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter": "/something horrible", "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )
    assert b"is not a valid XPath expression" in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data


# actually only really used by the distll.io importer, but could be handy too
def test_check_with_prefix_css_filter(client, live_server):
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

    # Give the endpoint time to spin up
    time.sleep(1)

    set_original_response()

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    time.sleep(3)

    res = client.post(
        url_for("edit_page", uuid="first"),
        data={"css_filter":  "xpath://*[contains(@class, 'sametext')]", "url": test_url, "tag": "", "headers": "", 'fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    time.sleep(3)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"Some text thats the same" in res.data #in selector
    assert b"Some text that will change" not in res.data #not in selector

    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
