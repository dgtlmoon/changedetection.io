#!/usr/bin/env python3
"""The "Browsers & Proxies" area: two pages under /settings, each a tab that is a real route
(/settings/browsers, /settings/proxies), and the proxies list that moved there from /settings."""
from flask import url_for
from .util import live_server_setup


def _proxy_rows(datastore):
    """The proxies added in the UI, as stored - without the empty rows the form pads with."""
    return [(p['proxy_name'], p['proxy_url'])
            for p in datastore.data['settings']['requests'].get('extra_proxies') or []
            if p.get('proxy_name') or p.get('proxy_url')]


def test_browsers_and_proxies_are_two_routed_tabs(client, live_server, measure_memory_usage, datastore_path):
    browsers_url = url_for("ui.browser_config.browsers_overview")
    proxies_url = url_for("settings.proxies_page")
    assert browsers_url == '/settings/browsers'
    assert proxies_url == '/settings/proxies'
    # The browser pages moved with it
    assert url_for("ui.browser_config.browser_config_add", base_fetcher='html_requests') == '/settings/browsers/add/html_requests'
    assert url_for("ui.browser_config.browser_config_edit", config_id='abc') == '/settings/browsers/edit/abc'

    browsers_tab = f'<a href="{browsers_url}">Browsers</a>'
    proxies_tab = f'<a href="{proxies_url}">Proxies</a>'

    # Each page carries both tabs as links to the routes (no #anchors), its own marked active
    res = client.get(browsers_url)
    assert res.status_code == 200
    html = res.data.decode()
    assert f'<li class="tab active">{browsers_tab}</li>' in html
    assert f'<li class="tab">{proxies_tab}</li>' in html

    res = client.get(proxies_url)
    assert res.status_code == 200
    html = res.data.decode()
    assert f'<li class="tab">{browsers_tab}</li>' in html
    assert f'<li class="tab active">{proxies_tab}</li>' in html
    assert 'name="requests-extra_proxies-0-proxy_name"' in html

    # One entry in the left action bar for both, lit on either page
    for url in (browsers_url, proxies_url):
        html = client.get(url).data.decode()
        entry = html[html.index(f'<a href="{browsers_url}"\n'):][:400]
        assert 'action-sidebar-item active' in entry
        assert 'Browsers &amp; Proxies' in entry

    # The old address still gets there
    res = client.get('/browsers')
    assert res.status_code == 302 and res.headers['Location'].endswith(browsers_url)


def test_proxies_are_saved_on_their_own_page(client, live_server, measure_memory_usage, datastore_path):
    """The proxies list left /settings: it is added, validated and saved at /settings/proxies,
    and saving the main settings neither shows it nor wipes it."""
    datastore = client.application.config.get('DATASTORE')
    proxies_url = url_for("settings.proxies_page")

    res = client.post(proxies_url, data={
        "requests-extra_proxies-0-proxy_name": "My proxy",
        "requests-extra_proxies-0-proxy_url": "http://user:pass@proxy.example:3128",
        "requests-extra_proxies-1-proxy_name": "Second",
        "requests-extra_proxies-1-proxy_url": "socks5://proxy2.example:1080",
    }, follow_redirects=True)
    assert b"Settings updated." in res.data
    assert _proxy_rows(datastore) == [("My proxy", "http://user:pass@proxy.example:3128"),
                                      ("Second", "socks5://proxy2.example:1080")]
    # Back on the page, filled in
    assert b'value="My proxy"' in res.data
    # ...and offered to watches (the proxy list is built from what was saved)
    assert {p['label'] for p in datastore.proxy_list.values()} >= {"My proxy", "Second"}

    # /settings no longer has the tab or the fields, but still offers them as the default proxy
    res = client.get(url_for("settings.settings_page"))
    assert b'requests-extra_proxies' not in res.data
    assert b'CAPTCHA' not in res.data
    assert b'name="requests-proxy"' in res.data and b'My proxy' in res.data
    assert f'href="{proxies_url}"'.encode() in res.data

    # Saving the main settings leaves the proxies alone
    res = client.post(url_for("settings.settings_page"), data={
        "requests-time_between_check-minutes": 180,
        "application-ignore_whitespace": "y",
    }, follow_redirects=True)
    assert b"Settings updated." in res.data
    assert len(_proxy_rows(datastore)) == 2

    # Refused, with the reason, and nothing changed: a wrong scheme, a name with no address
    for bad, message in (
        ({"requests-extra_proxies-0-proxy_name": "Bad", "requests-extra_proxies-0-proxy_url": "ftp://nope.example"},
         b"Proxy URLs must start with"),
        # ...left empty, as a browser posts it, or not posted at all
        ({"requests-extra_proxies-0-proxy_name": "Only a name", "requests-extra_proxies-0-proxy_url": ""},
         b"Both a name, and a Proxy URL is required."),
        ({"requests-extra_proxies-0-proxy_name": "Only a name"},
         b"Both a name, and a Proxy URL is required."),
        ({"requests-extra_proxies-0-proxy_url": "http://no-name.example:3128"},
         b"Both a name, and a Proxy URL is required."),
    ):
        res = client.post(proxies_url, data=bad, follow_redirects=True)
        assert message in res.data
        assert b"Settings updated." not in res.data
        assert len(_proxy_rows(datastore)) == 2

    # Emptying the rows removes them
    res = client.post(proxies_url, data={"requests-extra_proxies-0-proxy_name": "", "requests-extra_proxies-0-proxy_url": ""},
                      follow_redirects=True)
    assert b"Settings updated." in res.data
    assert _proxy_rows(datastore) == []
