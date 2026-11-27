#!/usr/bin/env python3
"""
A watch's own files (screenshot, favicon, visual selector data) need a login when a password is set.
The password can be kept in the settings or given in the environment as SALTED_PASS, and these files
were only protected for the first.
"""
import base64
import hashlib
import os

from flask import url_for

PNG_1PX = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')


def _salted_pass(password):
    """What SALTED_PASS holds: base64 of a 32 byte salt followed by the derived key."""
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return base64.b64encode(salt + key).decode('ascii')


def test_per_watch_files_need_login_with_salted_pass(app, client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    watch = datastore.data['watching'][uuid]
    watch.ensure_data_dir_exists()
    with open(os.path.join(watch.data_dir, 'last-screenshot.png'), 'wb') as f:
        f.write(PNG_1PX)
    watch.bump_favicon(url="https://site.test/favicon.png", favicon_base_64=base64.b64encode(PNG_1PX).decode())

    per_watch_files = {
        group: url_for('static_content', group=group, filename=uuid)
        for group in ('screenshot', 'favicon', 'visual_selector_data')
    }

    # No password anywhere: open, as before
    anonymous = app.test_client(use_cookies=True)
    assert anonymous.get(per_watch_files['screenshot']).status_code == 200
    assert anonymous.get(per_watch_files['favicon']).status_code == 200

    # Password given in the environment only, nothing in the settings
    monkeypatch.setenv("SALTED_PASS", _salted_pass("env-password"))
    assert not datastore.data['settings']['application'].get('password')

    for group, url in per_watch_files.items():
        assert anonymous.get(url).status_code == 403, f"{group} was served without a login"

    # The pages still load what they need: the app's own static files stay open (the login page uses them)
    assert anonymous.get(url_for('static_content', group='js', filename='jquery-3.6.0.min.js')).status_code == 200

    # A shared diff page shows the screenshot to someone who is not logged in, that stays
    datastore.data['settings']['application']['shared_diff_access'] = True
    assert anonymous.get(per_watch_files['screenshot']).status_code == 200
    datastore.data['settings']['application']['shared_diff_access'] = False

    # Logged in: served
    logged_in = app.test_client(use_cookies=True)
    res = logged_in.post(url_for("login"), data={"password": "env-password"}, follow_redirects=True)
    assert b"/logout" in res.data
    assert logged_in.get(per_watch_files['screenshot']).status_code == 200
    assert logged_in.get(per_watch_files['favicon']).status_code == 200
    assert logged_in.get(per_watch_files['visual_selector_data']).status_code != 403

    monkeypatch.delenv("SALTED_PASS")
    datastore.delete(uuid)
