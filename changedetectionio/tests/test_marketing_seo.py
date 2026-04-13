#!/usr/bin/env python3
"""Tests for the public marketing blueprint and the SEO meta stack.

Verifies that:
* Marketing routes render and return 200.
* base.html emits the full SEO stack (title, description, OG, Twitter,
  canonical, keywords, JSON-LD) on a public page.
* base.html emits ``noindex,nofollow`` on non-public app pages.
* robots.txt disallows the app surfaces and advertises the sitemap.
* sitemap.xml is well-formed and lists the four public routes.
"""

from flask import url_for


def _get_ok(client, endpoint, **kwargs):
    res = client.get(url_for(endpoint, **kwargs), follow_redirects=False)
    assert res.status_code == 200, (
        f"{endpoint} returned {res.status_code}: {res.data[:200]!r}"
    )
    return res.data.decode("utf-8")


def test_landing_page_renders_and_is_indexable(client, live_server, measure_memory_usage, datastore_path):
    body = _get_ok(client, "marketing.landing")
    assert "onChange by Sairo" in body
    assert "Know when the web changes" in body
    # Public pages must NOT have noindex.
    assert 'content="noindex,nofollow"' not in body
    assert 'content="index,follow"' in body
    # Full meta stack present.
    assert '<meta property="og:title"' in body
    assert '<meta property="og:description"' in body
    assert '<meta property="og:image"' in body
    assert '<meta name="twitter:card"' in body
    assert '<link rel="canonical"' in body
    # JSON-LD SoftwareApplication schema.
    assert '"@type": "SoftwareApplication"' in body


def test_features_page_mentions_site_inventory(client, live_server, measure_memory_usage, datastore_path):
    body = _get_ok(client, "marketing.features")
    # New feature should be front-and-centre on /features.
    assert "Site URL inventory" in body
    # Anchor for the landing page "How it works" link must exist.
    assert 'id="site-inventory"' in body


def test_about_and_privacy_render(client, live_server, measure_memory_usage, datastore_path):
    about = _get_ok(client, "marketing.about")
    assert "changedetection.io" in about  # attribution must be present

    privacy = _get_ok(client, "marketing.privacy")
    assert "Privacy" in privacy
    # robots.txt reference in privacy page uses url_for, so it resolves
    assert "/robots.txt" in privacy


def test_robots_txt_disallows_app_surfaces(client, live_server, measure_memory_usage, datastore_path):
    res = client.get(url_for("marketing.robots_txt"))
    assert res.status_code == 200
    assert res.mimetype == "text/plain"
    body = res.data.decode("utf-8")
    # Every app surface must be disallowed.
    for path in ("/edit/", "/diff/", "/preview/", "/api/", "/settings", "/login"):
        assert f"Disallow: {path}" in body, f"missing Disallow: {path}"
    # Sitemap URL must be advertised.
    assert "Sitemap: " in body
    assert "/sitemap.xml" in body


def test_sitemap_xml_is_valid_and_lists_public_routes(client, live_server, measure_memory_usage, datastore_path):
    res = client.get(url_for("marketing.sitemap_xml"))
    assert res.status_code == 200
    assert res.mimetype == "application/xml"
    body = res.data.decode("utf-8")

    # Well-formed XML — parse it.
    from xml.etree import ElementTree as ET
    root = ET.fromstring(body)
    ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    assert root.tag == f"{ns}urlset"

    locs = [el.text for el in root.iter(f"{ns}loc")]
    # All four public pages must be listed.
    for endpoint in ("marketing.landing", "marketing.features", "marketing.about", "marketing.privacy"):
        expected = url_for(endpoint, _external=True)
        assert expected in locs, f"sitemap missing {endpoint} -> {expected}"


def test_app_pages_remain_noindex(client, live_server, measure_memory_usage, datastore_path):
    # The watchlist is the canonical "app" page; it must still be noindex
    # even if reachable, to protect the watch inventory from crawlers.
    res = client.get(url_for("watchlist.index"), follow_redirects=True)
    # Either we get the watchlist HTML (no password) or we got redirected to
    # the login page. In both cases, noindex must appear in the response.
    body = res.data.decode("utf-8")
    assert 'content="noindex,nofollow"' in body
