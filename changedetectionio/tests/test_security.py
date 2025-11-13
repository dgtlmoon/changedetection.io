import os

from flask import url_for

from changedetectionio.tests.util import set_modified_response
from .util import live_server_setup, wait_for_all_checks, delete_all_watches
from .. import strtobool


def set_original_response(datastore_path):
    test_return_data = """<html>
    <head><title>head title</title></head>
    <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <span class="foobar-detection" style='display:none'></span>
     </body>
     </html>
    """

    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(test_return_data)
    return None

def test_bad_access(client, live_server, measure_memory_usage, datastore_path):

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
              "body": "",
              "time_between_check_use_default": "y"},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted or invalid URL format' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": '            javascript:alert(123)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted or invalid URL format' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": '%20%20%20javascript:alert(123)%20%20', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted or invalid URL format' in res.data


    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": ' source:javascript:alert(document.domain)', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted or invalid URL format' in res.data

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": 'https://i-wanna-xss-you.com?hereis=<script>alert(1)</script>', "tags": ''},
        follow_redirects=True
    )

    assert b'Watch protocol is not permitted or invalid URL format' in res.data

def _runner_test_various_file_slash(client, file_uri):

    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": file_uri, "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))

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

    delete_all_watches(client)

def test_file_slash_access(client, live_server, measure_memory_usage, datastore_path):
    

    # file: is NOT permitted by default, so it will be caught by ALLOW_FILE_URI check

    test_file_path = os.path.abspath(__file__)
    _runner_test_various_file_slash(client, file_uri=f"file://{test_file_path}")
#    _runner_test_various_file_slash(client, file_uri=f"file:/{test_file_path}")
#    _runner_test_various_file_slash(client, file_uri=f"file:{test_file_path}") # CVE-2024-56509

def test_xss(client, live_server, measure_memory_usage, datastore_path):
    
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

    # Check that even forcing an update directly still doesnt get to the frontend
    set_original_response(datastore_path=datastore_path)
    XSS_HACK = 'javascript:alert(document.domain)'
    uuid = client.application.config.get('DATASTORE').add_watch(url=url_for('test_endpoint', _external=True))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    live_server.app.config['DATASTORE'].data['watching'][uuid]['url']=XSS_HACK


    res = client.get(url_for("ui.ui_views.preview_page", uuid=uuid))
    assert XSS_HACK.encode('utf-8') not in res.data and res.status_code == 200
    client.get(url_for("ui.ui_views.diff_history_page", uuid=uuid))
    assert XSS_HACK.encode('utf-8') not in res.data and res.status_code == 200
    res = client.get(url_for("watchlist.index"))
    assert XSS_HACK.encode('utf-8') not in res.data and res.status_code == 200


def test_xss_watch_last_error(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "include_filters": '<a href="https://foobar"></a><script>alert(123);</script>',
            "url": url_for('test_endpoint', _external=True),
            'fetch_backend': "html_requests",
            "time_between_check_use_default": "y"
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    res = client.get(url_for("watchlist.index"))

    assert b"<script>alert(123);</script>" not in res.data  # this text should be there
    assert b'&lt;a href=&#34;https://foobar&#34;&gt;&lt;/a&gt;&lt;script&gt;alert(123);&lt;/script&gt;' in res.data
    assert b"https://foobar" in res.data # this text should be there

def test_valid_redirect(client, live_server, measure_memory_usage, datastore_path):
    import_url = url_for('imports.import_page')
    _test_redirect_url(client, redirect_url=import_url, expected_url=import_url)

def test_external_url_redirect(client, live_server, measure_memory_usage, datastore_path):
    _test_redirect_url(client, 'https://some-domain.tld')

def test_double_slash_redirect(client, live_server, measure_memory_usage, datastore_path):
    _test_redirect_url(client, '//some-domain.tld')

def test_url_with_at_symbol_redirect(client, live_server, measure_memory_usage, datastore_path):
    _test_redirect_url(client, '//@evil.com')

def test_section_url_redirect(client, live_server, measure_memory_usage, datastore_path):
    _test_redirect_url(client, '#fake')

def test_different_protocol_redirect(client, live_server, measure_memory_usage, datastore_path):
    _test_redirect_url(client, 'ms-teams://backups')

def _test_redirect_url(client, redirect_url, expected_url = None):
    # Enable password check
    res = client.post(
        url_for("settings.settings_page"),
        data={"application-password": "foobar"},
        follow_redirects=True
    )
    assert b"Password protection enabled." in res.data

    res = client.post(
        url_for("login"),
        data={
            "password": "foobar",
            "redirect": redirect_url
        },
        follow_redirects=False
    )

    assert res.status_code == 302
    assert res.location == (expected_url or url_for('watchlist.index'))
