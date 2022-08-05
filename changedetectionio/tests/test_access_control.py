from flask import url_for
from . util import live_server_setup

def test_check_access_control(app, client):
    # Still doesnt work, but this is closer.

    with app.test_client(use_cookies=True) as c:
        # Check we don't have any password protection enabled yet.
        res = c.get(url_for("settings_page"))
        assert b"Remove password" not in res.data

        # Enable password check.
        res = c.post(
            url_for("settings_page"),
            data={"application-password": "foobar",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        assert b"Password protection enabled." in res.data

        # Check we hit the login
        res = c.get(url_for("index"), follow_redirects=True)

        assert b"Login" in res.data

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
            url_for("settings_page"),
            data={
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        res = c.get(url_for("logout"),
            follow_redirects=True)

        res = c.get(url_for("settings_page"),
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

        res = c.get(url_for("settings_page"))

        # Menu should be available now
        assert b"SETTINGS" in res.data
        assert b"BACKUP" in res.data
        assert b"IMPORT" in res.data
        assert b"LOG OUT" in res.data
        assert b"time_between_check-minutes" in res.data
        assert b"fetch_backend" in res.data

        ##################################################
        # Remove password button, and check that it worked
        ##################################################
        res = c.post(
            url_for("settings_page"),
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
            url_for("settings_page"),
            data={"application-password": "",
                  "requests-time_between_check-minutes": 180,
                  'application-fetch_backend': "html_requests"},
            follow_redirects=True
        )

        assert b"Password protection enabled" not in res.data

