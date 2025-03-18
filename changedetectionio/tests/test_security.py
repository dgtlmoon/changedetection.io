import os

from flask import url_for
from .util import live_server_setup, wait_for_all_checks
from .. import strtobool


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

def test_bad_access(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": 'https://localhost'},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Attempt to add a body with a GET method
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
              "url": 'javascript:alert(document.domain)',
              "tags": "",
              "method": "GET",
              "fetch_backend": "html_requests",
              "body": ""},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": '            javascript:alert(123)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": '%20%20%20javascript:alert(123)%20%20', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data


    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": ' source:javascript:alert(document.domain)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data


def _runner_test_various_file_slash(client, file_uri):

    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": file_uri, "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("index"))

    substrings = [b"URLs with hostname components are not permitted", b"No connection adapters were found for"]


    # If it is enabled at test time
    if strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
        if file_uri.startswith('file:///'):
            # This one should be the full qualified path to the file and should get the contents of this file
            res = client.get(
                url_for("ui.ui_views.preview_page", uuid="first"),
                follow_redirects=True
            )
            assert b'_runner_test_various_file_slash' in res.data
        else:
            # This will give some error from requests or if it went to chrome, will give some other error :-)
            assert any(s in res.data for s in substrings)

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_file_slash_access(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    # file: is NOT permitted by default, so it will be caught by ALLOW_FILE_URI check

    test_file_path = os.path.abspath(__file__)
    _runner_test_various_file_slash(client, file_uri=f"file://{test_file_path}")
    _runner_test_various_file_slash(client, file_uri=f"file:/{test_file_path}")
    _runner_test_various_file_slash(client, file_uri=f"file:{test_file_path}") # CVE-2024-56509

def test_xss(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    from changedetectionio.notification import (
        default_notification_format
    )
    # the template helpers were named .jinja which meant they were not having jinja2 autoescape enabled.
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-notification_urls": '"><img src=x onerror=alert(document.domain)>',
              "application-notification_title": '"><img src=x onerror=alert(document.domain)>',
              "application-notification_body": '"><img src=x onerror=alert(document.domain)>',
              "application-notification_format": default_notification_format,
              "requests-time_between_check-minutes": 180,
              'application-fetch_backend': "html_requests"},
        follow_redirects=True
    )

    assert b"<img src=x onerror=alert(" not in res.data
    assert b"&lt;img" in res.data

