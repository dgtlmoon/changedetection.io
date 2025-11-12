#!/usr/bin/env python3
import os
import time
from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client, delete_all_watches
from loguru import logger
from ..blueprint.rss import RSS_FORMAT_TYPES


def set_original_cdata_xml(datastore_path):
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

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)



def set_html_content(datastore_path, content):
    test_return_data = f"""<html>
       <body>
     Some initial text<br>
     <p>{content}</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    # Write as UTF-8 encoded bytes
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "wb") as f:
        f.write(test_return_data.encode('utf-8'))

# def test_setup(client, live_server, measure_memory_usage, datastore_path):
   #  live_server_setup(live_server) # Setup on conftest per function

def test_rss_and_token(client, live_server, measure_memory_usage, datastore_path):
    #   #  live_server_setup(live_server) # Setup on conftest per function

    set_original_response(datastore_path=datastore_path)
    rss_token = extract_rss_token_from_UI(client)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_random_content_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    time.sleep(1)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Add our URL to the import page
    res = client.get(
        url_for("rss.feed", token="bad token", _external=True),
        follow_redirects=True
    )

    assert b"Access denied, bad token" in res.data

    res = client.get(
        url_for("rss.feed", token=rss_token, _external=True),
        follow_redirects=True
    )
    assert b"Access denied, bad token" not in res.data
    assert b"Random content" in res.data

    client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)

def test_basic_cdata_rss_markup(client, live_server, measure_memory_usage, datastore_path):
    

    set_original_cdata_xml(datastore_path)
    # Rarely do endpoints give the right header, usually just text/xml, so we check also for <rss
    # This also triggers the automatic CDATA text parser so the RSS goes back a nice content list
    test_url = url_for('test_endpoint', content_type="text/xml; charset=UTF-8", _external=True)

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b'CDATA' not in res.data
    assert b'<![' not in res.data
    assert b'Hackers can access your computer' in res.data
    assert b'The days of Terminator' in res.data
    delete_all_watches(client)

def test_rss_xpath_filtering(client, live_server, measure_memory_usage, datastore_path):
    

    set_original_cdata_xml(datastore_path)

    test_url = url_for('test_endpoint', content_type="application/atom+xml; charset=UTF-8", _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )
    assert b"Watch added in Paused state, saving will unpause" in res.data

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid, unpause_on_save=1),
        data={
                "include_filters": "//item/title",
                "fetch_backend": "html_requests",
                "headers": "",
                "proxy": "no-proxy",
                "tags": "",
                "url": test_url,
                "time_between_check_use_default": "y",
              },
        follow_redirects=True
    )
    assert b"unpaused" in res.data

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
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

    delete_all_watches(client)


def test_rss_bad_chars_breaking(client, live_server, measure_memory_usage, datastore_path):
    """This should absolutely trigger the RSS builder to go into worst state mode

    - source: prefix means no html conversion (which kinda filters out the bad stuff)
    - Binary data
    - Very long so that the saving is performed by Brotli (and decoded back to bytes)

    Otherwise feedgen should support regular unicode
    """
    

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        ten_kb_string = "A" * 10_000
        f.write(ten_kb_string)

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "source:"+test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Set the bad content
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        jpeg_bytes = "\xff\xd8\xff\xe0\x00\x10XXXXXXXX\x00\x01\x02\x00\x00\x01\x00\x01\x00\x00"  # JPEG header
        jpeg_bytes += "A" * 10_000

        f.write(jpeg_bytes)

    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert b'Queued 1 watch for rechecking.' in res.data
    wait_for_all_checks(client)
    rss_token = extract_rss_token_from_UI(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    i=0
    from loguru import logger
    # Because chardet could take a long time
    while i<=10:
        logger.debug(f"History was {live_server.app.config['DATASTORE'].data['watching'][uuid].history_n}..")
        if live_server.app.config['DATASTORE'].data['watching'][uuid].history_n ==2:
            break
            i+=1
        time.sleep(2)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n == 2

    # Check RSS feed is still working
    res = client.get(
        url_for("rss.feed", uuid=uuid, token=rss_token),
        follow_redirects=False # Important! leave this off! it should not redirect
    )
    assert res.status_code == 200

    #assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n == 2
    #assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n == 2


def test_rss_single_watch_feed(client, live_server, measure_memory_usage, datastore_path):

    app_rss_token = live_server.app.config['DATASTORE'].data['settings']['application'].get('rss_access_token')
    rss_content_format = live_server.app.config['DATASTORE'].data['settings']['application'].get('rss_content_format')

    set_original_response(datastore_path=datastore_path)


    test_url = url_for('test_endpoint', _external=True)
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(
        url_for('rss.rss_single_watch', uuid=uuid, token=app_rss_token),
        follow_redirects=False
    )

    assert res.status_code == 400
    assert b'not have enough history' in res.data

    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(
        url_for('rss.rss_single_watch', uuid=uuid, token=app_rss_token),
        follow_redirects=False
    )
    assert res.status_code == 200
    import xml.etree.ElementTree as ET
    root = ET.fromstring(res.data)

    def check_formatting(expected_type, content, url):
        logger.debug(f"Checking formatting type {expected_type}")
        if expected_type == 'text':
            assert '<p>' not in content
            assert 'body' not in content
            assert '(changed) Which is across multiple lines\n'
            assert 'modified head title had a change.' # Because it picked it up <title> as watch_title in default template
        elif expected_type == 'html':
            assert '<p>' in content
            assert '<body>' in content
            assert '<p>(changed) Which is across multiple lines<br>' in content
            assert f'href="{url}">modified head title had a change.</a>'
        elif expected_type == 'htmlcolor':
            assert '<body>' in content
            assert ' role="note" aria-label="Changed text" title="Changed text">Which is across multiple lines</span>' in content
            assert f'href="{url}">modified head title had a change.</a>'
        else:
            raise Exception(f"Unknown type {expected_type}")


    item = root.findall('.//item')[0].findtext('description')
    check_formatting(expected_type=rss_content_format, content=item, url=test_url)

    # Now the default one is over, lets try all the others
    for k in list(RSS_FORMAT_TYPES.keys()):
        res = client.post(
            url_for("settings.settings_page"),
            data={"application-rss_content_format": k},
            follow_redirects=True
        )
        assert b'Settings updated' in res.data

        res = client.get(
            url_for('rss.rss_single_watch', uuid=uuid, token=app_rss_token),
            follow_redirects=False
        )
        assert res.status_code == 200
        root = ET.fromstring(res.data)
        item = root.findall('.//item')[0].findtext('description')
        check_formatting(expected_type=k, content=item, url=test_url)

