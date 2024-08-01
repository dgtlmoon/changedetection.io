#!/usr/bin/env python3

import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client


def set_original_cdata_xml():
    test_return_data = """<rss xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
    <channel>
    <title>Gizi</title>
    <link>https://test.com</link>
    <atom:link href="https://testsite.com" rel="self" type="application/rss+xml"/>
    <description>
    <![CDATA[ The Future Could Be Here ]]>
    </description>
    <language>en</language>
    <item>
    <title>
    <![CDATA[ <img src="https://testsite.com/hacked.jpg"> Hackers can access your computer ]]>
    </title>
    <link>https://testsite.com/news/12341234234</link>
    <description>
    <![CDATA[ <img class="type:primaryImage" src="https://testsite.com/701c981da04869e.jpg"/><p>The days of Terminator and The Matrix could be closer. But be positive.</p><p><a href="https://testsite.com">Read more link...</a></p> ]]>
    </description>
    <category>cybernetics</category>
    <category>rand corporation</category>
    <pubDate>Tue, 17 Oct 2023 15:10:00 GMT</pubDate>
    <guid isPermaLink="false">1850933241</guid>
    <dc:creator>
    <![CDATA[ Mr Hacker News ]]>
    </dc:creator>
    <media:thumbnail url="https://testsite.com/thumbnail-c224e10d81488e818701c981da04869e.jpg"/>
    </item>

    <item>
        <title>    Some other title    </title>
        <link>https://testsite.com/news/12341234236</link>
        <description>
        Some other description
        </description>
    </item>    
    </channel>
    </rss>
            """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

def test_rss_and_token(client, live_server, measure_memory_usage):
    #    live_server_setup(live_server)

    set_original_response()
    rss_token = extract_rss_token_from_UI(client)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_random_content_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    set_modified_response()
    time.sleep(1)
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.get(
        url_for("rss", token="bad token", _external=True),
        follow_redirects=True
    )

    assert b"Access denied, bad token" in res.data

    res = client.get(
        url_for("rss", token=rss_token, _external=True),
        follow_redirects=True
    )
    assert b"Access denied, bad token" not in res.data
    assert b"Random content" in res.data

    client.get(url_for("form_delete", uuid="all"), follow_redirects=True)

def test_basic_cdata_rss_markup(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_original_cdata_xml()

    test_url = url_for('test_endpoint', content_type="application/xml", _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'CDATA' not in res.data
    assert b'<![' not in res.data
    assert b'Hackers can access your computer' in res.data
    assert b'The days of Terminator' in res.data
    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)

def test_rss_xpath_filtering(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_original_cdata_xml()

    test_url = url_for('test_endpoint', content_type="application/xml", _external=True)

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    uuid = extract_UUID_from_client(client)
    res = client.post(
        url_for("edit_page", uuid=uuid, unpause_on_save=1),
        data={
                "include_filters": "//item/title",
                "fetch_backend": "html_requests",
                "headers": "",
                "proxy": "no-proxy",
                "tags": "",
                "url": test_url,
              },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'CDATA' not in res.data
    assert b'<![' not in res.data
    # #1874  All but the first <title was getting selected
    # Convert any HTML with just a top level <title> to <h1> to be sure title renders

    assert b'Hackers can access your computer' in res.data # Should ONLY be selected by the xpath
    assert b'Some other title' in res.data  # Should ONLY be selected by the xpath
    assert b'The days of Terminator' not in res.data # Should NOT be selected by the xpath
    assert b'Some other description' not in res.data  # Should NOT be selected by the xpath

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
