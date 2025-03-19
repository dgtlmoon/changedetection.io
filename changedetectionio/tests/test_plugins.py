from flask import url_for

from changedetectionio.tests.util import live_server_setup


def test_checkplugins_registered(live_server, client):
    live_server_setup(live_server)
    res = client.get(
        url_for("settings.settings_page")
    )
    assert res.status_code == 200
    # Should be registered in the info table
    assert b'<td>Webpage Text/HTML, JSON and PDF changes' in res.data
    assert b'<td>text_json_diff' in res.data

