#!/usr/bin/env python3
"""The login cookies say SameSite=Lax themselves, they don't rely on the browser's default."""

from flask import url_for


def test_login_cookies_are_samesite_lax(app, client, live_server, measure_memory_usage, datastore_path):
    c = app.test_client(use_cookies=True)
    res = c.post(
        url_for("settings.settings_page"),
        data={"application-password": "foobar",
              "requests-time_between_check-minutes": 180,
              "application-fetch_backend": "html_requests"},
        follow_redirects=True,
    )
    assert b"Password protection enabled." in res.data

    # A wrong password is still refused, the right one still logs in (the comparison is constant-time now)
    res = c.post(url_for("login"), data={"password": "not-the-password"}, follow_redirects=True)
    assert b"Incorrect password" in res.data

    res = c.post(url_for("login"), data={"password": "foobar"})
    assert res.status_code == 302
    cookies = {h.split('=', 1)[0]: h for h in res.headers.getlist('Set-Cookie')}
    assert 'remember_token' in cookies and 'session' in cookies
    for name in ('remember_token', 'session'):
        assert 'SameSite=Lax' in cookies[name], f"{name} cookie should be SameSite=Lax: {cookies[name]}"
        assert 'HttpOnly' in cookies[name], f"{name} cookie should be HttpOnly: {cookies[name]}"

    client.application.config.get('DATASTORE').remove_password()
