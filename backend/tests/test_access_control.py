from flask import url_for


def test_check_access_control(app, client):
    # Still doesnt work, but this is closer.

    with app.test_client() as c:
        # Check we dont have any password protection enabled yet.
        res = c.get(url_for("settings_page"))
        assert b"Remove password" not in res.data

        # Enable password check.
        res = c.post(
            url_for("settings_page"),
            data={"password": "foobar", "minutes_between_check": 180},
            follow_redirects=True
        )

        assert b"Password protection enabled." in res.data
        assert b"LOG OUT" not in res.data

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

        assert b"LOG OUT" in res.data
        res = c.get(url_for("settings_page"))

        # Menu should be available now
        assert b"SETTINGS" in res.data
        assert b"BACKUP" in res.data
        assert b"IMPORT" in res.data
        assert b"LOG OUT" in res.data

        # Now remove the password so other tests function, @todo this should happen before each test automatically
        res = c.get(url_for("settings_page", removepassword="yes"),
              follow_redirects=True)
        assert b"Password protection removed." in res.data

        res = c.get(url_for("index"))
        assert b"LOG OUT" not in res.data


# There was a bug where saving the settings form would submit a blank password
def test_check_access_control_no_blank_password(app, client):
    # Still doesnt work, but this is closer.

    with app.test_client() as c:
        # Check we dont have any password protection enabled yet.
        res = c.get(url_for("settings_page"))
        assert b"Remove password" not in res.data

        # Enable password check.
        res = c.post(
            url_for("settings_page"),
            data={"password": "", "minutes_between_check": 180},
            follow_redirects=True
        )

        assert b"Password protection enabled." not in res.data
        assert b"Login" not in res.data


# There was a bug where saving the settings form would submit a blank password
def test_check_access_no_remote_access_to_remove_password(app, client):
    # Still doesnt work, but this is closer.

    with app.test_client() as c:
        # Check we dont have any password protection enabled yet.
        res = c.get(url_for("settings_page"))
        assert b"Remove password" not in res.data

        # Enable password check.
        res = c.post(
            url_for("settings_page"),
            data={"password": "password", "minutes_between_check": 180},
            follow_redirects=True
        )

        assert b"Password protection enabled." in res.data
        assert b"Login" in res.data

        res = c.get(url_for("settings_page", removepassword="yes"),
              follow_redirects=True)
        assert b"Password protection removed." not in res.data

        res = c.get(url_for("index"),
              follow_redirects=True)
        assert b"watch-table-wrapper" not in res.data
