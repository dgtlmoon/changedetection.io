#!/usr/bin/env python3
"""
Settings > General offers a QR code pointing at this instance.

Installing the PWA on a phone otherwise means typing something like
https://example.com/my-instance/ on a phone keyboard, sub-path and
all - which is the real barrier to the Android share target ever getting used.

Only shown over HTTPS, because that is a hard requirement for installing a PWA: offering it
on a plain-http instance sends people to a page with no Install option and no explanation.
"""

import io
import os

import segno

from changedetectionio.blueprint.pwa.service import HTTPS_OVERRIDE_ENV, https_mode

QR_URL = '/settings/pwa-install-qrcode.svg'


def test_qr_is_served_as_svg(client, live_server):
    res = client.get(QR_URL, base_url='https://localhost/')
    assert res.status_code == 200
    assert res.headers['Content-Type'].startswith('image/svg+xml')
    assert b'<svg' in res.data


def test_qr_encodes_this_instance(client, live_server):
    """Pins the payload. The render parameters are duplicated on purpose - if someone
    retunes them, this fails loudly rather than silently shipping an unscannable code."""
    res = client.get(QR_URL, base_url='https://localhost/')

    expected = io.BytesIO()
    segno.make('https://localhost/', error='m').save(
        expected, kind='svg', scale=4, border=2, dark='#000000', light='#ffffff')

    assert res.data == expected.getvalue()

    # ...and it is genuinely instance-specific, not a constant
    other = io.BytesIO()
    segno.make('https://somewhere-else.example.com/', error='m').save(
        other, kind='svg', scale=4, border=2, dark='#000000', light='#ffffff')
    assert res.data != other.getvalue()


def test_qr_points_at_the_requested_host_not_the_configured_one(client, live_server):
    """url_for(_external=True) builds from SERVER_NAME, so behind a reverse proxy it emitted
    the internal address and the QR sent the phone somewhere it couldn't reach. It has to
    come from the request, sub-path included."""
    res = client.get(QR_URL, base_url='https://example.com/my-instance/')

    expected = io.BytesIO()
    segno.make('https://example.com/my-instance/', error='m').save(
        expected, kind='svg', scale=4, border=2, dark='#000000', light='#ffffff')
    assert res.data == expected.getvalue()


def test_qr_only_offered_over_https(client, live_server):
    """A PWA can't be installed over plain http, so the offer would be a dead end."""
    assert b'pwa-install-qr' not in client.get('/settings').data

    secure = client.get('/settings', base_url='https://localhost/')
    assert b'pwa-install-qr' in secure.data
    assert b'Install on your phone' in secure.data


def test_https_detection_can_be_overridden():
    """Terminating TLS at a proxy that doesn't send X-Forwarded-Proto, or running without
    USE_X_SETTINGS, makes an installable instance look like plain http."""
    assert https_mode(is_secure=True) is True
    assert https_mode(is_secure=False) is False

    previous = os.environ.get(HTTPS_OVERRIDE_ENV)
    try:
        os.environ[HTTPS_OVERRIDE_ENV] = 'True'
        assert https_mode(is_secure=False) is True, "override must be able to force it on"

        os.environ[HTTPS_OVERRIDE_ENV] = 'False'
        assert https_mode(is_secure=True) is False, "and back off again"

        os.environ[HTTPS_OVERRIDE_ENV] = ''
        assert https_mode(is_secure=False) is False, "empty is not an override"
    finally:
        os.environ.pop(HTTPS_OVERRIDE_ENV, None)
        if previous is not None:
            os.environ[HTTPS_OVERRIDE_ENV] = previous


def test_override_reveals_the_qr_on_a_plain_http_instance(client, live_server):
    previous = os.environ.get(HTTPS_OVERRIDE_ENV)
    os.environ[HTTPS_OVERRIDE_ENV] = 'True'
    try:
        assert b'pwa-install-qr' in client.get('/settings').data
    finally:
        os.environ.pop(HTTPS_OVERRIDE_ENV, None)
        if previous is not None:
            os.environ[HTTPS_OVERRIDE_ENV] = previous
