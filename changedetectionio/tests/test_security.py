import os

from flask import url_for
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks
import time

from .. import strtobool


def test_setup(client, live_server, measure_memory_usage):
    live_server_setup(live_server)

def test_bad_access(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    res = client.post(
        url_for("import_page"),
        data={"urls": 'https://localhost'},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Attempt to add a body with a GET method
    res = client.post(
        url_for("edit_page", uuid="first"),
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
        url_for("form_quick_watch_add"),
        data={"url": '            javascript:alert(123)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data

    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": '%20%20%20javascript:alert(123)%20%20', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data


    res = client.post(
        url_for("form_quick_watch_add"),
        data={"url": ' source:javascript:alert(document.domain)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted by SAFE_PROTOCOL_REGEX' in res.data


def test_file_slashslash_access(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    test_file_path = os.path.abspath(__file__)

    # file:// is permitted by default, but it will be caught by ALLOW_FILE_URI
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": f"file://{test_file_path}", "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("index"))

    # If it is enabled at test time
    if strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
        res = client.get(
            url_for("preview_page", uuid="first"),
            follow_redirects=True
        )

        assert b"test_file_slashslash_access" in res.data
    else:
        # Default should be here
        assert b'file:// type access is denied for security reasons.' in res.data

def test_file_slash_access(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    test_file_path = os.path.abspath(__file__)

    # file:// is permitted by default, but it will be caught by ALLOW_FILE_URI
    client.post(
        url_for("form_quick_watch_add"),
        data={"url": f"file:/{test_file_path}", "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("index"))

    # If it is enabled at test time
    if strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
        # So it should permit it, but it should fall back to the 'requests' library giving an error
        # (but means it gets passed to playwright etc)
        assert b"URLs with hostname components are not permitted" in res.data
    else:
        # Default should be here
        assert b'file:// type access is denied for security reasons.' in res.data

def test_xss(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)
    from changedetectionio.notification import (
        default_notification_format
    )
    # the template helpers were named .jinja which meant they were not having jinja2 autoescape enabled.
    res = client.post(
        url_for("settings_page"),
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

