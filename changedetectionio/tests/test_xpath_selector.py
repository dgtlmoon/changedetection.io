# -*- coding: utf-8 -*-


from flask import url_for
from .util import  wait_for_all_checks, delete_all_watches
from ..processors.magic import RSS_XML_CONTENT_TYPES
import os


def set_rss_atom_feed_response(datastore_path, header='', ):
    test_return_data = f"""{header}<!-- Generated on Wed, 08 Oct 2025 08:42:33 -0700, really really honestly  -->
<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
<channel>
    <atom:link href="https://store.waterpowered.com/news/collection//" rel="self" type="application/rss+xml"/>
    <title>RSS Feed</title>
    <link>
        <![CDATA[ https://store.waterpowered.com/news/collection// ]]>
    </link>
    <description>
        <![CDATA[ Events and Announcements for ]]>
    </description>
    <language>en-us</language>
    <generator>water News RSS</generator>
    <item>
        <title> 🍁 Lets go discount</title>
        <description><p class="bb_paragraph">ok heres the description</p></description>
        <link>
        <![CDATA[ https://store.waterpowered.com/news/app/1643320/view/511845698831908921 ]]>
        </link>
        <pubDate>Wed, 08 Oct 2025 15:28:55 +0000</pubDate>
        <guid isPermaLink="true">https://store.waterpowered.com/news/app/1643320/view/511845698831908921</guid>
        <enclosure url="https://clan.fastly.waterstatic.com/images/40721482/42822e5f00b2becf520ace9500981bb56f3a89f2.jpg" length="0" type="image/jpeg"/>
    </item>
</channel>
</rss>"""

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    return None



def set_original_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None


def set_modified_response(datastore_path):
    test_return_data = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  THIS CHANGES AND SHOULDNT TRIGGER A CHANGE<br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some new text</div>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)

    return None


# Handle utf-8 charset replies https://github.com/dgtlmoon/changedetection.io/pull/613
def test_check_xpath_filter_utf8(client, live_server, measure_memory_usage, datastore_path):
    filter = '//item/*[self::description]'

    d = '''<?xml version="1.0" encoding="UTF-8"?>
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(d)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True, content_type="application/rss+xml;charset=UTF-8")
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": filter, "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'Unicode strings with encoding declaration are not supported.' not in res.data
    delete_all_watches(client)


# Handle utf-8 charset replies https://github.com/dgtlmoon/changedetection.io/pull/613
def test_check_xpath_text_function_utf8(client, live_server, measure_memory_usage, datastore_path):
    filter = '//item/title/text()'

    d = '''<?xml version="1.0" encoding="UTF-8"?>
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(d)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True, content_type="application/rss+xml;charset=UTF-8")
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": filter, "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'Unicode strings with encoding declaration are not supported.' not in res.data

    # The service should echo back the request headers
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'Stock Alert (UK): RPi CM4' in res.data
    assert b'Stock Alert (UK): Big monitor' in res.data

    delete_all_watches(client)


def test_check_markup_xpath_filter_restriction(client, live_server, measure_memory_usage, datastore_path):
    xpath_filter = "//*[contains(@class, 'sametext')]"

    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # Goto the edit page, add our ignore text
    # Add our URL to the import page
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": xpath_filter, "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # view it/reset state back to viewed
    client.get(url_for("ui.ui_diff.diff_history_page", uuid="first"), follow_redirects=True)

    #  Make a change
    set_modified_response(datastore_path=datastore_path)

    # Trigger a check
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    # Give the thread time to pick it up
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'has-unread-changes' not in res.data
    delete_all_watches(client)


def test_xpath_validation(client, live_server, measure_memory_usage, datastore_path):
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "/something horrible", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"is not a valid XPath expression" in res.data
    delete_all_watches(client)


def test_xpath23_prefix_validation(client, live_server, measure_memory_usage, datastore_path):
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "xpath:/something horrible", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"is not a valid XPath expression" in res.data
    delete_all_watches(client)

def test_xpath1_lxml(client, live_server, measure_memory_usage, datastore_path):
    

    d = '''<?xml version="1.0" encoding="UTF-8"?>
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
    			<title>Stock Alert (UK): Big monitorěěěě</title>
    			<foo>something else unrelated</foo>
    		</item>		
    	</channel>
    </rss>'''.encode('utf-8')

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "wb") as f:
        f.write(d)


    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "xpath1://title/text()", "url": test_url, "tags": "", "headers": "",
              'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    ##### #2312
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))
    assert b'_ElementStringResult' not in res.data # tested with 5.1.1 when it was removed and 5.1.0
    assert b'Exception' not in res.data
    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"rpilocator.com" in res.data  # in selector
    assert "Stock Alert (UK): Big monitorěěěě".encode('utf-8') in res.data  # not in selector

    #####


def test_xpath1_validation(client, live_server, measure_memory_usage, datastore_path):
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "xpath1:/something horrible", "url": test_url, "tags": "", "headers": "", 'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )
    assert b"is not a valid XPath expression" in res.data
    delete_all_watches(client)


# actually only really used by the distll.io importer, but could be handy too
def test_check_with_prefix_include_filters(client, live_server, measure_memory_usage, datastore_path):
    delete_all_watches(client)

    set_original_response(datastore_path=datastore_path)
    wait_for_all_checks(client)
    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "xpath://*[contains(@class, 'sametext')]", "url": test_url, "tags": "", "headers": "",
              'fetch_backend': "html_requests", "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"Some text thats the same" in res.data  # in selector
    assert b"Some text that will change" not in res.data  # not in selector

    delete_all_watches(client)


def test_various_rules(client, live_server, measure_memory_usage, datastore_path):
    # Just check these don't error
    ##  live_server_setup(live_server) # Setup on conftest per function
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write("""<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <div class="sametext">Some text thats the same</div>
     <div class="changetext">Some text that will change</div>
     <a href=''>some linky </a>
     <a href=''>another some linky </a>
     <!-- related to https://github.com/dgtlmoon/changedetection.io/pull/1774 -->
     <input   type="email"   id="email" />     
     </body>
     </html>
    """)

    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    for r in ['//div', '//a', 'xpath://div', 'xpath://a']:
        res = client.post(
            url_for("ui.ui_edit.edit_page", uuid="first"),
            data={"include_filters": r,
                  "url": test_url,
                  "tags": "",
                  "headers": "",
                  'fetch_backend': "html_requests",
                  "time_between_check_use_default": "y"},
            follow_redirects=True
        )
        wait_for_all_checks(client)
        assert b"Updated watch." in res.data
        res = client.get(url_for("watchlist.index"))
        assert b'fetch-error' not in res.data, f"Should not see errors after '{r} filter"

    delete_all_watches(client)


def test_xpath_20(client, live_server, measure_memory_usage, datastore_path):
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    set_original_response(datastore_path=datastore_path)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={"include_filters": "//*[contains(@class, 'sametext')]|//*[contains(@class, 'changetext')]",
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )

    assert b"Some text thats the same" in res.data  # in selector
    assert b"Some text that will change" in res.data  # in selector

    delete_all_watches(client)


def test_xpath_20_function_count(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "xpath:count(//div) * 123456789987654321",
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"246913579975308642" in res.data  # in selector

    delete_all_watches(client)


def test_xpath_20_function_count2(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={"include_filters": "/html/body/count(div) * 123456789987654321",
              "url": test_url,
              "tags": "",
              "headers": "",
              'fetch_backend': "html_requests",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"246913579975308642" in res.data  # in selector

    delete_all_watches(client)


def test_xpath_20_function_string_join_matches(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)

    # Add our URL to the import page
    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "include_filters": "xpath:string-join(//*[contains(@class, 'sametext')]|//*[matches(@class, 'changetext')], 'specialconjunction')",
            "url": test_url,
            "tags": "",
            "headers": "",
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid=uuid),
        follow_redirects=True
    )

    assert b"Some text thats the samespecialconjunctionSome text that will change" in res.data  # in selector

    delete_all_watches(client)


def _subtest_xpath_rss(client, datastore_path, content_type='text/html'):

    # Add our URL to the import page
    test_url = url_for('test_endpoint', content_type=content_type, _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first", unpause_on_save=1),
        data={
            "url": test_url,
            "include_filters": "xpath://item",
            "tags": '',
            "fetch_backend": "html_requests",
            "time_between_check_use_default": "y",
        },
        follow_redirects=True
    )

    assert b"unpaused" in res.data
    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"Lets go discount" in res.data, f"When testing for Lets go discount called with content type '{content_type}'"
    assert b"Events and Announcements" not in res.data, f"When testing for Lets go discount called with content type '{content_type}'" # It should not be here because thats not our selector target

    delete_all_watches(client)

# Be sure all-in-the-wild types of RSS feeds work with xpath
def test_rss_xpath(client, live_server, measure_memory_usage, datastore_path):
    for feed_header in ['', '<?xml version="1.0" encoding="utf-8"?>']:
        set_rss_atom_feed_response(header=feed_header, datastore_path=datastore_path)
        for content_type in RSS_XML_CONTENT_TYPES:
            _subtest_xpath_rss(client, content_type=content_type, datastore_path=datastore_path)
