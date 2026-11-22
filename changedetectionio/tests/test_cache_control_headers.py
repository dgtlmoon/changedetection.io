#!/usr/bin/env python3
"""
PR #4319: dynamic pages went out with no Cache-Control at all.

Flask does send "Vary: Cookie" on any response that touched the session, so a
spec-compliant shared cache would already key these per-session. An edge cache
configured to key purely on URL ignores that, and one reporter's Cloudflare
Worker did exactly that: it cached /settings, including the csrf_token embedded
in the form, and every later save failed with "The CSRF tokens do not match" -
or, worse, could hand one session's authenticated page to another visitor.

An app-wide after_request fills in Cache-Control when the route didn't set one,
so the explicit headers on assets/screenshots/favicons still win.
"""

import re


def test_dynamic_pages_are_not_storable(client, live_server):
    # Any page carrying session state or a CSRF token - the cached copy is what
    # breaks form submits and leaks across sessions.
    for path in ['/', '/settings', '/login']:
        response = client.get(path)
        cache_control = response.headers.get('Cache-Control')
        assert cache_control is not None, (
            f"{path} sent no Cache-Control - a URL-keyed edge cache is free to store and "
            f"replay it, stale CSRF token and all"
        )
        assert 'no-store' in cache_control, (
            f"{path} must not be storable by an intermediary, got {cache_control!r}"
        )


def test_routes_keep_their_own_cache_control(client, live_server):
    # The hook only fills in a missing header, so routes that deliberately
    # allow caching must come through untouched.

    # static_content() sets its own header on assets (see the two tests below), so they
    # never reach the hook at all.
    response = client.get('/static/styles/styles.css')
    assert response.status_code == 200
    assert 'no-store' not in response.headers.get('Cache-Control', ''), (
        f"static assets should keep werkzeug's own header, got "
        f"{response.headers.get('Cache-Control')!r}"
    )

    # And a route with an explicit long-lived, publicly cacheable header.
    response = client.get('/static/flags/4x3/ad.svg')
    assert response.status_code == 200
    assert response.headers.get('Cache-Control') == 'max-age=86400, public', (
        f"flag SVGs set their own 24h public cache header, got "
        f"{response.headers.get('Cache-Control')!r}"
    )


def test_static_assets_are_cacheable(client, live_server):
    # Assets used to go out as "no-cache, max-age=0", so every CSS/JS/image on every page
    # load cost a request (a 304, but still a round trip). url_for() now fingerprints the
    # URL with the file's mtime+size, and a matching ?v= is what buys the long cache.
    res = client.get('/')
    assert res.status_code == 200

    versioned = re.findall(r'(/static/(?:js|styles|images|favicons)/[^"?]+\?v=[0-9-]+)', res.data.decode())
    assert versioned, "no fingerprinted asset URLs in the rendered page - ?v= is what unlocks caching"

    for url in set(versioned):
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers.get('Cache-Control') == 'public, max-age=31536000, immutable', (
            f"{url} is pinned to one file revision so it should be cacheable forever, got "
            f"{response.headers.get('Cache-Control')!r}"
        )
        # The session cookie is permanent and re-signed on every response, so its value keeps
        # changing - a "Vary: Cookie" here would miss the cache on every asset of every page load.
        assert 'cookie' not in response.headers.get('Vary', '').lower(), (
            f"{url} must not vary by cookie, got {response.headers.get('Vary')!r}"
        )
        assert 'Set-Cookie' not in response.headers, (
            f"{url} is publicly cacheable, it must not carry a session cookie"
        )
        assert response.headers.get('ETag'), f"{url} sent no ETag"


def test_unversioned_static_assets_still_revalidate(client, live_server):
    # Older cached HTML (or a hand-typed URL) has no ?v=, and a stale one must not be trusted
    # either - both have to keep revalidating so an upgrade can't serve the wrong file forever.
    for url in ['/static/js/toggle-theme.js', '/static/js/toggle-theme.js?v=1-1']:
        response = client.get(url)
        assert response.status_code == 200, url
        assert response.headers.get('Cache-Control') == 'public, max-age=0, must-revalidate', (
            f"{url} isn't pinned to a known file revision so it must be revalidated, got "
            f"{response.headers.get('Cache-Control')!r}"
        )
        etag = response.headers.get('ETag')
        assert etag, f"{url} sent no ETag - revalidation would re-download the whole file"
        # ETag is werkzeug's own mtime-size-path token, so revalidation is a cheap 304.
        assert client.get(url, headers={'If-None-Match': etag}).status_code == 304
