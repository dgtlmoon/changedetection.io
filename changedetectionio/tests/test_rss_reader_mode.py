#!/usr/bin/env python3

import time
import os

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client, delete_all_watches

def set_xmlns_purl_content(datastore_path, extra=""):
    data=f"""<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="https://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/" xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
<channel>
<atom:link href="https://www.xxxxxxxtechxxxxx.com/feeds.xml" rel="self" type="application/rss+xml"/>
<title>
<![CDATA[ Latest from xxxxxxxtechxxxxx ]]>
</title>
<link>https://www.xxxxx.com</link>
<description>
<![CDATA[ All the latest content from the xxxxxxxtechxxxxx team ]]>
</description>
<lastBuildDate>Wed, 19 Nov 2025 15:00:00 +0000</lastBuildDate>
<language>en</language>
<item>
<title>
<![CDATA[ Sony Xperia 1 VII review: has Sony’s long-standing Xperia family lost what it takes to compete? ]]>
</title>
<dc:content>
<![CDATA[  {{extra}}  a little harder, dc-content. blue often quite tough and purple usually very difficult.</p><p>On the plus side, you don't technically need to solve the final one, as you'll be able to answer that one by a process of elimination. What's more, you can make up to four mistakes, which gives you a little bit of breathing room.</p><p>It's a little more involved than something like Wordle, however, and there are plenty of opportunities for the game to trip you up with tricks. For instance, watch out for homophones and other word games that could disguise the answers.</p><p>It's playable for free via the <a href="https://www.nytimes.com/games/strands" target="_blank">NYT Games site</a> on desktop or mobile.</p></article></section> ]]>
</dc:content>
<link>https://www.xxxxxxx.com/gaming/nyt-connections-today-answers-hints-20-november-2025</link>
<description>
<![CDATA[ Looking for NYT Connections answers and hints? Here's all you need to know to solve today's game, plus my commentary on the puzzles. ]]>
</description>
<guid isPermaLink="false">N2C2T6DztpWdxSdKpSUx89</guid>
<enclosure url="https://cdn.mos.cms.futurecdn.net/RCGfdf3yhQ9W3MHbTRT6yk-1280-80.jpg" type="image/jpeg" length="0"/>
<pubDate>Wed, 19 Nov 2025 15:00:00 +0000</pubDate>
<category>
<![CDATA[ Gaming ]]>
</category>
<dc:creator>
<![CDATA[ Johnny Dee ]]>
</dc:creator>
<media:content type="image/jpeg" url="https://cdn.mos.cms.futurecdn.net/RCGfdf3yhQ9W3MHbTRT6yk-1280-80.jpg">
<media:credit>
<![CDATA[ New York Times ]]>
</media:credit>
<media:text>
<![CDATA[ NYT Connections homescreen on a phone, on a purple background ]]>
</media:text>
<media:title type="plain">
<![CDATA[ NYT Connections homescreen on a phone, on a purple background ]]>
</media:title>
</media:content>
<media:thumbnail url="https://cdn.mos.cms.futurecdn.net/RCGfdf3yhQ9W3MHbTRT6yk-1280-80.jpg"/>
</item>
    </channel>
    </rss>
            """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(data)




def set_original_cdata_xml(datastore_path):
    test_return_data = """<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
<channel>
<title>Security Bulletins on wetscale</title>
<link>https://wetscale.com/security-bulletins/</link>
<description>Recent security bulletins from wetscale</description>
<lastBuildDate>Fri, 10 Oct 2025 14:58:11 GMT</lastBuildDate>
<docs>https://validator.w3.org/feed/docs/rss2.html</docs>
<generator>wetscale.com</generator>
<language>en-US</language>
<copyright>© 2025 wetscale Inc. All rights reserved.</copyright>
<atom:link href="https://wetscale.com/security-bulletins/index.xml" rel="self" type="application/rss+xml"/>
<item>
<title>TS-2025-005</title>
<link>https://wetscale.com/security-bulletins/#ts-2025-005</link>
<guid>https://wetscale.com/security-bulletins/#ts-2025-005</guid>
<pubDate>Thu, 07 Aug 2025 00:00:00 GMT</pubDate>
<description><p>Wet noodles escape<br><p>they also found themselves outside</p> </description>
</item>


<item>
<title>TS-2025-004</title>
<link>https://wetscale.com/security-bulletins/#ts-2025-004</link>
<guid>https://wetscale.com/security-bulletins/#ts-2025-004</guid>
<pubDate>Tue, 27 May 2025 00:00:00 GMT</pubDate>
<description>
    <![CDATA[ <img class="type:primaryImage" src="https://testsite.com/701c981da04869e.jpg"/><p>The days of Terminator and The Matrix could be closer. But be positive.</p><p><a href="https://testsite.com">Read more link...</a></p> ]]>
</description>
</item>
    </channel>
    </rss>
            """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)



def test_rss_reader_mode(client, live_server, measure_memory_usage, datastore_path):
    set_original_cdata_xml(datastore_path=datastore_path)

    # Rarely do endpoints give the right header, usually just text/xml, so we check also for <rss
    # This also triggers the automatic CDATA text parser so the RSS goes back a nice content list
    test_url = url_for('test_endpoint', content_type="text/xml; charset=UTF-8", _external=True)
    live_server.app.config['DATASTORE'].data['settings']['application']['rss_reader_mode'] = True


    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)


    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    dates = list(watch.history.keys())
    snapshot_contents = watch.get_history_snapshot(timestamp=dates[0])
    assert 'Wet noodles escape' in snapshot_contents
    assert '<br>' not in snapshot_contents
    assert '&lt;' not in snapshot_contents
    assert 'The days of Terminator and The Matrix' in snapshot_contents
    assert 'PubDate: Thu, 07 Aug 2025 00:00:00 GMT' in snapshot_contents
    delete_all_watches(client)

def test_rss_reader_mode_with_css_filters(client, live_server, measure_memory_usage, datastore_path):
    set_original_cdata_xml(datastore_path=datastore_path)

    # Rarely do endpoints give the right header, usually just text/xml, so we check also for <rss
    # This also triggers the automatic CDATA text parser so the RSS goes back a nice content list
    test_url = url_for('test_endpoint', content_type="text/xml; charset=UTF-8", _external=True)
    live_server.app.config['DATASTORE'].data['settings']['application']['rss_reader_mode'] = True


    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'include_filters': [".last"]})
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)


    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    dates = list(watch.history.keys())
    snapshot_contents = watch.get_history_snapshot(timestamp=dates[0])
    assert 'Wet noodles escape' not in snapshot_contents
    assert '<br>' not in snapshot_contents
    assert '&lt;' not in snapshot_contents
    assert 'The days of Terminator and The Matrix' in snapshot_contents
    delete_all_watches(client)


def test_xmlns_purl_content(client, live_server, measure_memory_usage, datastore_path):
    set_xmlns_purl_content(datastore_path=datastore_path)

    # Rarely do endpoints give the right header, usually just text/xml, so we check also for <rss
    # This also triggers the automatic CDATA text parser so the RSS goes back a nice content list
    #test_url = url_for('test_endpoint', content_type="text/xml; charset=UTF-8", _external=True)

    # Because NO utf-8 was specified here, we should be able to recover it in requests or other somehow.
    test_url = url_for('test_endpoint', content_type="text/xml;", _external=True)
    live_server.app.config['DATASTORE'].data['settings']['application']['rss_reader_mode'] = True

    # Add our URL to the import page
    uuid = client.application.config.get('DATASTORE').add_watch(url=test_url, extras={'include_filters': [".last"]})
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    watch = live_server.app.config['DATASTORE'].data['watching'][uuid]
    dates = list(watch.history.keys())
    snapshot_contents = watch.get_history_snapshot(timestamp=dates[0])
    assert "Title: Sony Xperia 1 VII review: has Sony’s long-standing Xperia family lost what it takes to compete?" in snapshot_contents
    assert "dc-content" in snapshot_contents
