from .util import live_server_setup, wait_for_all_checks
from flask import url_for
import time

def test_check_access_control(app, client, live_server, measure_memory_usage, datastore_path):
    # Still doesnt work, but this is closer.
   #  live_server_setup(live_server) # Setup on conftest per function

    with app.test_client(use_cookies=True) as c:
        # Check we don't have any password protection enabled yet.
        res = c.get(url_for("settings.settings_page"))
        assert b"Remove password" not in res.data

        # add something that we can hit via diff page later
        res = c.post(
            url_for("imports.import_page"),
            data={"urls": url_for('test_random_content_endpoint', _external=True)},
            follow_redirects=True
        )

        assert b"1 Imported" in res.data
        # causes a 'Popped wrong request context.' error when client. is accessed?
        wait_for_all_checks(client)

        res = c.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        assert b'Queued 1 watch for rechecking.' in res.data
        wait_for_all_checks(client)


        # Enable password check and diff page access bypass
        res = c.post(
            url_for("settings.settings_page"),
            data={"application-password": "foobar",
                  "application-shared_diff_access": "True",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        assert b"Password protection enabled." in res.data

        # Check we hit the login
        res = c.get(url_for("watchlist.index"), follow_redirects=True)
        # Should be logged out
        assert b"Login" in res.data

        # The diff page should return something valid when logged out
        res = c.get(url_for("ui.ui_diff.diff_history_page", uuid="first"))
        assert b'Random content' in res.data

        # GHSA-vwgh-2hvh-4xm5: shared_diff_access only covers the read-only
        # diff page — the extract endpoints (which run an attacker-supplied
        # regex against history and write a CSV to disk) must still require
        # auth even when the share flag is enabled.
        res = c.get(url_for("ui.ui_diff.diff_history_page_extract_GET", uuid="first"))
        assert res.status_code == 302, "Extract form GET must redirect to login for anonymous users"
        assert b'/login' in res.data or b'login' in res.headers.get('Location', '').encode()

        res = c.post(
            url_for("ui.ui_diff.diff_history_page_extract_POST", uuid="first"),
            data={"extract_regex": ".*", "extract_submit_button": "Extract as CSV"},
        )
        assert res.status_code == 302, "Extract POST must redirect to login for anonymous users"
        assert b'login' in res.headers.get('Location', '').encode()

        # But sub-resources the diff page legitimately loads should still pass the gate.
        # download_patch is linked from diff.html — anonymous viewers must be able to fetch it.
        # (We don't care about the body here, just that auth doesn't block it.)
        res = c.get(url_for("ui.ui_diff.download_patch", uuid="first"))
        assert res.status_code != 302, "download_patch must be reachable for shared diff viewers"

        # processor_asset (used for screenshots embedded in image_ssim_diff watches) must also be reachable.
        # For a text watch the processor has no such asset so 404 is fine — what matters is no auth redirect.
        res = c.get(url_for("ui.ui_diff.processor_asset", uuid="first", asset_name="before"))
        assert res.status_code != 302, "processor_asset must be reachable for shared diff viewers"

        # access to assets should work (check_authentication)
        res = c.get(url_for('static_content', group='js', filename='jquery-3.6.0.min.js'))
        assert res.status_code == 200
        res = c.get(url_for('static_content', group='styles', filename='styles.css'))
        assert res.status_code == 200
        res = c.get(url_for('static_content', group='styles', filename='404-testetest.css'))
        assert res.status_code == 404

        # Access to screenshots should be limited by 'shared_diff_access'
        path = url_for('static_content', group='screenshot', filename='random-uuid-that-will-404.png', _external=True)
        res = c.get(path)
        assert res.status_code == 404

        # Check wrong password does not let us in
        res = c.post(
            url_for("login"),
            data={"password": "WRONG PASSWORD"},
            follow_redirects=True
        )

        assert b"LOG OUT" not in res.data
        assert b"Incorrect password" in res.data


        # Menu should not be available yet
        #        assert b"SETTINGS" not in res.data
        #        assert b"BACKUP" not in res.data
        #        assert b"IMPORT" not in res.data

        # defaultuser@changedetection.io is actually hardcoded for now, we only use a single password
        res = c.post(
            url_for("login"),
            data={"password": "foobar"},
            follow_redirects=True
        )

        # Yes we are correctly logged in
        assert b"LOG OUT" in res.data

        # 598 - Password should be set and not accidently removed
        res = c.post(
            url_for("settings.settings_page"),
            data={
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        res = c.get(url_for("logout"),
            follow_redirects=True)

        assert b"Login" in res.data

        res = c.get(url_for("settings.settings_page"),
            follow_redirects=True)


        assert b"Login" in res.data

        res = c.get(url_for("login"))
        assert b"Login" in res.data


        res = c.post(
            url_for("login"),
            data={"password": "foobar"},
            follow_redirects=True
        )

        # Yes we are correctly logged in
        assert b"LOG OUT" in res.data

        res = c.get(url_for("settings.settings_page"))

        # Menu should be available now
        assert b"SETTINGS" in res.data
        assert b"IMPORT" in res.data
        assert b"LOG OUT" in res.data
        assert b"time_between_check-minutes" in res.data
        assert b"fetch_backend" in res.data

        ##################################################
        # Remove password button, and check that it worked
        ##################################################
        res = c.post(
            url_for("settings.settings_page"),
            data={
                "requests-time_between_check-minutes": 180,
                "application-fetch_backend": "html_webdriver",
                "application-removepassword_button": "Remove password"
            },
            follow_redirects=True,
        )
        assert b"Password protection removed." in res.data
        assert b"LOG OUT" not in res.data

        ############################################################
        # Be sure a blank password doesnt setup password protection
        ############################################################
        res = c.post(
            url_for("settings.settings_page"),
            data={"application-password": "",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        assert b"Password protection enabled" not in res.data

        # Now checking the diff access
        # Enable password check and diff page access bypass
        res = c.post(
            url_for("settings.settings_page"),
            data={"application-password": "foobar",
                  # Should be disabled
                  "application-shared_diff_access": "",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        assert b"Password protection enabled." in res.data

        # Check we hit the login
        res = c.get(url_for("watchlist.index"), follow_redirects=True)
        # Should be logged out
        assert b"Login" in res.data

        # Access to screenshots should be limited by 'shared_diff_access'
        res = c.get(url_for('static_content', group='screenshot', filename='random-uuid-that-will-403.png'))
        assert res.status_code == 403

        # The diff page should return something valid when logged out
        res = c.get(url_for("ui.ui_diff.diff_history_page", uuid="first"))
        assert b'Random content' not in res.data
