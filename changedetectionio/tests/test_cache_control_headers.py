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

    # send_from_directory() always sets Cache-Control itself, so static files
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
