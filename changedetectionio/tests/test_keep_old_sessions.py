#!/usr/bin/env python3
"""KEEP_OLD_SESSIONS keeps browsers that logged in before logins carried the password's fingerprint logged in
across the upgrade, until the password is next changed or removed."""

from flask import g, url_for
from flask_login.utils import encode_cookie

from changedetectionio.flask_app import USER_ID_FINGERPRINT_SEPARATOR

OLD_USER_ID = "defaultuser@changedetection.io"
MARKER = 'password_marker_at_login_fingerprint_upgrade'
SETTINGS_FORM = {
    "requests-time_between_check-minutes": 180,
    "application-fetch_backend": "html_requests",
}


def _forget_cached_user():
    # The test fixtures keep one app context open for the whole test, and Flask-Login caches the user it
    # loaded there. A real server gets a new one per request, so drop it or every browser shares one login.
    g.pop('_login_user', None)


def _set_password(c, password):
    _forget_cached_user()
    res = c.post(
        url_for("settings.settings_page"),
        data=dict(SETTINGS_FORM, **{"application-password": password}),
        follow_redirects=True,
    )
    assert b"Password protection enabled." in res.data


def _browser_with_old_cookie(app):
    # What an earlier version issued for "remember me": the bare user id, no password fingerprint
    c = app.test_client(use_cookies=True)
    c.set_cookie("remember_token", encode_cookie(OLD_USER_ID))
    return c


def _is_logged_in(c):
    _forget_cached_user()
    return c.get(url_for("settings.settings_page")).status_code == 200


def test_keep_old_sessions(app, client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    datastore = client.application.config.get('DATASTORE')
    application = datastore.data['settings']['application']
    admin = app.test_client(use_cookies=True)

    _set_password(admin, "first-password")

    # The upgrade records which password was set
    application.pop(MARKER, None)
    datastore.update_35()
    assert application.get(MARKER)
    assert application[MARKER] != application['password'], "The marker should not be a second copy of the password"

    # Off unless asked for
    monkeypatch.delenv("KEEP_OLD_SESSIONS", raising=False)
    assert not _is_logged_in(_browser_with_old_cookie(app))

    monkeypatch.setenv("KEEP_OLD_SESSIONS", "true")
    old_browser = _browser_with_old_cookie(app)
    assert _is_logged_in(old_browser)

    # ...and the browser was moved over to a cookie that carries the fingerprint, so it works without the setting
    assert USER_ID_FINGERPRINT_SEPARATOR in old_browser.get_cookie("remember_token").value.split('|', 1)[1]
    monkeypatch.delenv("KEEP_OLD_SESSIONS")
    assert _is_logged_in(old_browser)

    # The first password change ends the old cookies, same as any other login
    monkeypatch.setenv("KEEP_OLD_SESSIONS", "true")
    _forget_cached_user()
    res = admin.post(url_for("login"), data={"password": "first-password"}, follow_redirects=True)
    assert b"/logout" in res.data
    _set_password(admin, "second-password")
    assert not _is_logged_in(_browser_with_old_cookie(app)), "An old cookie should not outlive a password change"
    assert not _is_logged_in(old_browser)

    # Nothing recorded at upgrade (no password was set then) means no old cookie is accepted
    application.pop(MARKER, None)
    assert not _is_logged_in(_browser_with_old_cookie(app))

    # Leave the datastore without a password for the next test
    application.pop(MARKER, None)
    datastore.remove_password()
