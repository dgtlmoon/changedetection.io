from flask import url_for

from changedetectionio.tests.util import wait_for_all_checks


def test_check_plugin_processor(client, live_server, measure_memory_usage, datastore_path):
    # requires os-int intelligence plugin installed (first basic one we test with)

    res = client.get(url_for("watchlist.index"))
    assert b'OSINT Reconnaissance' in res.data

    assert b'<input checked id="processor-0" name="processor" type="radio" value="text_json_diff">' in res.data, "But the first text_json_diff processor should always be selected by default in quick watch form"

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": 'http://127.0.0.1', "tags": '', 'processor': 'osint_recon'},
        follow_redirects=True
    )
    assert b"Watch added" in res.data
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    res = client.get(
        url_for("ui.ui_preview.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b'Target: http://127.0.0.1' in res.data
    assert b'DNSKEY Records' in res.data