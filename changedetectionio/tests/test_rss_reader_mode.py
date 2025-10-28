#!/usr/bin/env python3

import time
import os

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_rss_token_from_UI, \
    extract_UUID_from_client, delete_all_watches


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
    snapshot_contents = watch.get_history_snapshot(dates[0])
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
    snapshot_contents = watch.get_history_snapshot(dates[0])
    assert 'Wet noodles escape' not in snapshot_contents
    assert '<br>' not in snapshot_contents
    assert '&lt;' not in snapshot_contents
    assert 'The days of Terminator and The Matrix' in snapshot_contents
    delete_all_watches(client)

