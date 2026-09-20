#!/usr/bin/env python3
"""
The PWA manifest moved out of static/favicons/site.webmanifest (where it arrived in 2022 as
favicon-generator output, 3a8a41a3f) and onto a route, so that:

  - its URLs can be relative. A manifest's scope defaults to its own directory and relative
    URLs resolve against the manifest's URL, so serving it from the app root is what lets an
    instance proxied at https://example.com/my-instance/ scope itself correctly without being
    told its own prefix. From /static/favicons/ the whole app would have been scoped to the
    favicons directory,
  - it can vary its name per instance, so co-tenanted sub-path installs are distinguishable
    in the Android share sheet,
  - it gets Content-Type: application/manifest+json, which send_from_directory cannot do
    (Python's mimetypes has no .webmanifest entry).

Also covers the maskable icon's safe zone, because a maskable icon that overflows it is
clipped by the launcher and there is no way to notice that from a test that only checks
the JSON.
"""

import json
import math
import os

from PIL import Image

FAVICON_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'favicons')


def _manifest(client, **kwargs):
    response = client.get('/site.webmanifest', **kwargs)
    assert response.status_code == 200
    return json.loads(response.data)


def test_manifest_served_as_manifest_json(client, live_server):
    response = client.get('/site.webmanifest')
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('application/manifest+json'), (
        f"got {response.headers['Content-Type']!r} - a static file would be "
        f"application/octet-stream here, which is the reason this is a route"
    )
    json.loads(response.data)  # must be valid JSON, not a Jinja-escaped near-miss


def test_manifest_urls_are_relative(client, live_server):
    """The whole point of the move: nothing in here may be root-anchored.

    An absolute "/" would send a sub-path instance's scope and start_url to the host root,
    which is outside its scope - the manifest is then invalid and the PWA won't install.
    """
    manifest = _manifest(client)

    for key in ('id', 'scope', 'start_url'):
        assert manifest[key] == './', f"{key} must be './' so it resolves to the instance root"

    for icon in manifest['icons']:
        assert not icon['src'].startswith(('/', 'http://', 'https://')), (
            f"icon src {icon['src']!r} is not relative - it would 404 on a sub-path install"
        )


def test_manifest_name_follows_the_subpath(client, live_server):
    """Co-tenanted instances share an origin, so identical names are indistinguishable
    in the share sheet and on the home screen."""
    default = _manifest(client)
    # The real product name, not an invented abbreviation - this is the home screen label,
    # and the name is the thing the project actually protects.
    assert default['name'] == 'changedetection.io'
    assert default['short_name'] == 'changedetection.io'

    tenant = _manifest(client, headers={'X-Forwarded-Prefix': '/acme-monitoring'})
    assert tenant['name'] == 'Acme Monitoring'
    assert tenant['short_name'] == 'Acme Monitoring'

    assert os.getenv('PWA_NAME') is None  # the override is env-only, nothing else sets it


def test_manifest_icons_exist_and_match_their_declared_sizes(client, live_server):
    manifest = _manifest(client)

    for icon in manifest['icons']:
        response = client.get('/' + icon['src'])
        assert response.status_code == 200, f"{icon['src']} declared in the manifest but not served"

        path = os.path.join(FAVICON_DIR, os.path.basename(icon['src']))
        width, height = Image.open(path).size
        assert f"{width}x{height}" == icon['sizes'], (
            f"{icon['src']} is {width}x{height} but the manifest claims {icon['sizes']} - "
            f"a lying size makes the browser pick the wrong icon"
        )

    # Chrome's install criteria need one icon of at least 144px
    assert any(int(i['sizes'].split('x')[0]) >= 144 for i in manifest['icons'])


def test_maskable_icon_clears_the_safe_zone(client, live_server):
    """Android crops maskable icons to the launcher's shape - circle, squircle, teardrop -
    and only guarantees a circle of 80% of the icon's width. The full-bleed art puts the
    white logo ring at 80.5% and 5px below centre, so declaring it maskable clipped the ring.
    This is the recentred, inset variant; if it is ever regenerated from the source without
    that correction, this catches it."""
    manifest = _manifest(client)

    maskable = [i for i in manifest['icons'] if 'maskable' in i['purpose'].split()]
    assert maskable, "no maskable icon - Android will letterbox the icon into a white tile"
    for icon in maskable:
        assert icon['purpose'] == 'maskable', (
            f"{icon['src']} declares {icon['purpose']!r}: one file cannot serve both, "
            f"'any' wants full-bleed and 'maskable' wants padding"
        )

        im = Image.open(os.path.join(FAVICON_DIR, os.path.basename(icon['src']))).convert('RGB')
        w, h = im.size
        px = im.load()
        safe_radius = 0.4 * w
        worst = 0
        for y in range(h):
            for x in range(w):
                r, g, b = px[x, y]
                if r > 200 and g > 200 and b > 200:  # the white logo ring and glyph
                    worst = max(worst, math.hypot(x - w / 2, y - h / 2))

        assert worst <= safe_radius, (
            f"{icon['src']}: logo reaches {worst:.1f}px from centre but the maskable safe "
            f"zone is {safe_radius:.1f}px - a circular launcher mask will clip it"
        )


def test_manifest_is_reachable_without_login(app, client, live_server, datastore_path):
    """A password-protected instance must still be installable. If the manifest redirects to
    /login the browser receives HTML where it expected JSON and silently drops the install
    option - with no error the operator would ever see."""
    with app.test_client(use_cookies=True) as c:
        res = c.post(
            "/settings",
            data={"application-password": "foobar",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )
        assert b"Password protection enabled." in res.data

        try:
            # Logged out from here on
            assert b"Login" in c.get("/", follow_redirects=True).data

            res = c.get('/site.webmanifest')
            assert res.status_code == 200, "manifest bounced to login - instance is un-installable"
            assert json.loads(res.data)['id'] == './'
        finally:
            c.post("/settings", data={"application-removepassword_button": "Remove password"},
                   follow_redirects=True)


def test_manifest_declares_a_share_target(client, live_server):
    """The share sheet entry is the whole point of installing on Android."""
    manifest = _manifest(client)

    share = manifest['share_target']
    assert share['action'] == './', "must be relative, and in scope, or the share 404s"
    assert share['method'] == 'GET', "a POST share target needs a service worker to intercept it"
    assert share['params'] == {
        'url': 'pwa_preset_url',
        'text': 'pwa_preset_text',
        'title': 'pwa_preset_title',
    }
