import os
from flask import url_for
from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client


def test_execute_custom_js(client, live_server, measure_memory_usage):

    live_server_setup(live_server)
    assert os.getenv('PLAYWRIGHT_DRIVER_URL'), "Needs PLAYWRIGHT_DRIVER_URL set for this test"

    test_url = url_for('test_interactive_html_endpoint', _external=True)
    test_url = test_url.replace('localhost.localdomain', 'cdio')
    test_url = test_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'edit_and_watch_submit_button': 'Edit > Watch'},
        follow_redirects=True
    )

    assert b"Watch added in Paused state, saving will unpause" in res.data

    res = client.post(
        url_for("edit_page", uuid="first", unpause_on_save=1),
        data={
            "url": test_url,
            "tags": "",
            'fetch_backend': "html_webdriver",
            'webdriver_js_execute_code': 'document.querySelector("button[name=test-button]").click();',
            'headers': "testheader: yes\buser-agent: MyCustomAgent",
        },
        follow_redirects=True
    )
    assert b"unpaused" in res.data
    wait_for_all_checks(client)

    uuid = extract_UUID_from_client(client)
    assert live_server.app.config['DATASTORE'].data['watching'][uuid].history_n >= 1, "Watch history had atleast 1 (everything fetched OK)"

    assert b"This text should be removed" not in res.data

    # Check HTML conversion detected and workd
    res = client.get(
        url_for("preview_page", uuid=uuid),
        follow_redirects=True
    )
    assert b"This text should be removed" not in res.data
    assert b"I smell JavaScript because the button was pressed" in res.data

    assert b"testheader: yes" in res.data
    assert b"user-agent: mycustomagent" in res.data

    client.get(
        url_for("form_delete", uuid="all"),
        follow_redirects=True
    )