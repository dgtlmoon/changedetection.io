#!/usr/bin/env python3
"""
The language modal renders for anonymous users on the login page (base.html keeps it
outside the `current_user.is_authenticated or not has_password` guard that wraps the
search modal). Both of its actions must therefore work while logged out.

Regression: only `set_language` was exempted in check_authentication(), so an anonymous
user at the login screen could pick a specific language but clicking "Auto-detect from
browser" right below it 302'd to /login without clearing the session locale.
"""

from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def test_language_endpoints_work_for_anonymous_users(client, live_server, measure_memory_usage, datastore_path):
    # Enable password protection so the global auth wall in check_authentication() is active
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-password": "hunter2",
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
        },
        follow_redirects=True)
    assert res.status_code == 200

    client.get(url_for("logout"), follow_redirects=True)

    # Both language links are rendered on the login page, so both must be reachable
    res = client.get(url_for("login"))
    assert res.status_code == 200
    assert b'language-selector' in res.data, "Language modal trigger should render for anonymous users"

    # Picking a specific language must not redirect to the login page
    res = client.get(url_for("set_language", locale="de"), follow_redirects=False)
    assert res.status_code == 302
    assert '/login' not in res.headers.get("Location", ""), \
        "set_language must not bounce anonymous users to /login"

    # ...and neither must clearing it back to auto-detect
    res = client.get(url_for("ui.delete_locale_language_session_var_if_it_exists"), follow_redirects=False)
    assert res.status_code == 302
    assert '/login' not in res.headers.get("Location", ""), \
        "Auto-detect must not bounce anonymous users to /login (it renders on the login page)"
