#!/usr/bin/env python3
"""Changing or removing the password signs out every other browser, not just the one making the change."""

from flask import g, url_for

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


def _login(c, password):
    _forget_cached_user()
    res = c.post(url_for("login"), data={"password": password}, follow_redirects=True)
    assert b"/logout" in res.data


def _is_logged_in(c):
    _forget_cached_user()
    return c.get(url_for("settings.settings_page")).status_code == 200


def test_password_change_signs_out_other_sessions(app, client, live_server, measure_memory_usage, datastore_path):
    # Separate browsers. Not used as context managers, nesting those mixes up their request contexts.
    admin = app.test_client(use_cookies=True)
    other_browser = app.test_client(use_cookies=True)
    remembered_browser = app.test_client(use_cookies=True)

    _set_password(admin, "first-password")
    _login(admin, "first-password")
    _login(other_browser, "first-password")
    assert _is_logged_in(other_browser)

    # A browser that was closed and reopened: the session cookie is gone, only "remember me" is left
    remember_token = other_browser.get_cookie("remember_token")
    assert remember_token, "Login should have issued a remember_token cookie"
    remembered_browser.set_cookie("remember_token", remember_token.value)
    assert _is_logged_in(remembered_browser)

    _set_password(admin, "second-password")

    assert not _is_logged_in(other_browser), "A session from the old password should be signed out"

    replayed_remember_token = app.test_client(use_cookies=True)
    replayed_remember_token.set_cookie("remember_token", remember_token.value)
    assert not _is_logged_in(replayed_remember_token), "A remember_token from the old password should not log in"

    # The old password is gone, the new one works
    _forget_cached_user()
    res = other_browser.post(url_for("login"), data={"password": "first-password"}, follow_redirects=True)
    assert b"Incorrect password" in res.data
    _login(other_browser, "second-password")
    assert _is_logged_in(other_browser)

    # Remove the password, then set the very same one again: sessions from before must not come back
    _login(admin, "second-password")
    _forget_cached_user()
    res = admin.post(
        url_for("settings.settings_page"),
        data=dict(SETTINGS_FORM, **{"application-removepassword_button": "Remove password"}),
        follow_redirects=True,
    )
    assert b"Password protection removed." in res.data
    _set_password(admin, "second-password")
    assert not _is_logged_in(other_browser), "A session from before the password was removed should be signed out"

    # Leave the datastore without a password for the next test
    client.application.config.get('DATASTORE').remove_password()
