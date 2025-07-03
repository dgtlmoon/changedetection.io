import json
import os
import time
from flask import url_for
from . util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks, extract_UUID_from_client



# Hard to just add more live server URLs when one test is already running (I think)
# So we add our test here (was in a different file)
def test_headers_in_request(client, live_server, measure_memory_usage):
    #ve_server_setup(live_server)
    # Add our URL to the import page
    test_url = url_for('test_headers', _external=True)
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        # Because its no longer calling back to localhost but from the browser container, set in test-only.yml
        test_url = test_url.replace('localhost', 'changedet')

    # Add the test URL twice, we will check
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    cookie_header = '_ga=GA1.2.1022228332; cookie-preferences=analytics:accepted;'


    # Add some headers to a request
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
              "url": test_url,
              "tags": "",
              "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
              "headers": "jinja2:{{ 1+1 }}\nxxx:ooo\ncool:yeah\r\ncookie:"+cookie_header},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data


    # Give the thread time to pick up the first version
    wait_for_all_checks(client)

    # The service should echo back the request headers
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    # Flask will convert the header key to uppercase
    assert b"Jinja2:2" in res.data
    assert b"Xxx:ooo" in res.data
    assert b"Cool:yeah" in res.data

    # The test call service will return the headers as the body
    from html import escape
    assert escape(cookie_header).encode('utf-8') in res.data

    wait_for_all_checks(client)

    # Re #137 -  It should have only one set of headers entered
    watches_with_headers = 0
    for k, watch in client.application.config.get('DATASTORE').data.get('watching').items():
            if (len(watch['headers'])):
                watches_with_headers += 1
    assert watches_with_headers == 1

    # 'server' http header was automatically recorded
    for k, watch in client.application.config.get('DATASTORE').data.get('watching').items():
        assert 'custom' in watch.get('remote_server_reply') # added in util.py

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_body_in_request(client, live_server, measure_memory_usage):

    # Add our URL to the import page
    test_url = url_for('test_body', _external=True)
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        # Because its no longer calling back to localhost but from the browser container, set in test-only.yml
        test_url = test_url.replace('localhost', 'cdio')

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # add the first 'version'
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
              "url": test_url,
              "tags": "",
              "method": "POST",
              "fetch_backend": "html_requests",
              "body": "something something"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)

    # Now the change which should trigger a change
    body_value = 'Test Body Value {{ 1+1 }}'
    body_value_formatted = 'Test Body Value 2'
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
              "url": test_url,
              "tags": "",
              "method": "POST",
              "fetch_backend": "html_requests",
              "body": body_value},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)

    # The service should echo back the body
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    # If this gets stuck something is wrong, something should always be there
    assert b"No history found" not in res.data
    # We should see the formatted value of what we sent in the reply
    assert str.encode(body_value) not in res.data
    assert str.encode(body_value_formatted) in res.data

    ####### data sanity checks
    # Add the test URL twice, we will check
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)
    watches_with_body = 0
    with open('test-datastore/url-watches.json') as f:
        app_struct = json.load(f)
        for uuid in app_struct['watching']:
            if app_struct['watching'][uuid]['body']==body_value:
                watches_with_body += 1

    # Should be only one with body set
    assert watches_with_body==1

    # Attempt to add a body with a GET method
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
              "url": test_url,
              "tags": "",
              "method": "GET",
              "fetch_backend": "html_requests",
              "body": "invalid"},
        follow_redirects=True
    )
    assert b"Body must be empty when Request Method is set to GET" in res.data
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_method_in_request(client, live_server, measure_memory_usage):
    # Add our URL to the import page
    test_url = url_for('test_method', _external=True)
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        # Because its no longer calling back to localhost but from the browser container, set in test-only.yml
        test_url = test_url.replace('localhost', 'cdio')

    # Add the test URL twice, we will check
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # Attempt to add a method which is not valid
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "",
            "fetch_backend": "html_requests",
            "method": "invalid"},
        follow_redirects=True
    )
    assert b"Not a valid choice" in res.data

    # Add a properly formatted body
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "",
            "fetch_backend": "html_requests",
            "method": "PATCH"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Give the thread time to pick up the first version
    wait_for_all_checks(client)

    # The service should echo back the request verb
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    # The test call service will return the verb as the body
    assert b"PATCH" in res.data

    wait_for_all_checks(client)

    watches_with_method = 0
    with open('test-datastore/url-watches.json') as f:
        app_struct = json.load(f)
        for uuid in app_struct['watching']:
            if app_struct['watching'][uuid]['method'] == 'PATCH':
                watches_with_method += 1

    # Should be only one with method set to PATCH
    assert watches_with_method == 1

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# Re #2408 - user-agent override test, also should handle case-insensitive header deduplication
def test_ua_global_override(client, live_server, measure_memory_usage):
    ##  live_server_setup(live_server) # Setup on conftest per function
    test_url = url_for('test_headers', _external=True)

    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-fetch_backend": "html_requests",
            "application-minutes_between_check": 180,
            "requests-default_ua-html_requests": "html-requests-user-agent"
        },
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"html-requests-user-agent" in res.data
    # default user-agent should have shown by now
    # now add a custom one in the headers


    # Add some headers to a request
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "testtag",
            "fetch_backend": 'html_requests',
            # Important - also test case-insensitive
            "headers": "User-AGent: agent-from-watch"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )
    assert b"agent-from-watch" in res.data
    assert b"html-requests-user-agent" not in res.data
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_headers_textfile_in_request(client, live_server, measure_memory_usage):
    
    # Add our URL to the import page

    webdriver_ua = "Hello fancy webdriver UA 1.0"
    requests_ua = "Hello basic requests UA 1.1"

    test_url = url_for('test_headers', _external=True)
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        # Because its no longer calling back to localhost but from the browser container, set in test-only.yml
        test_url = test_url.replace('localhost', 'cdio')

    form_data = {
        "application-fetch_backend": "html_requests",
        "application-minutes_between_check": 180,
        "requests-default_ua-html_requests": requests_ua
    }

    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        form_data["requests-default_ua-html_webdriver"] = webdriver_ua

    res = client.post(
        url_for("settings.settings_page"),
        data=form_data,
        follow_redirects=True
    )
    assert b'Settings updated' in res.data

    res = client.get(url_for("settings.settings_page"))

    # Only when some kind of real browser is setup
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        assert b'requests-default_ua-html_webdriver' in res.data

    # Field should always be there
    assert b"requests-default_ua-html_requests" in res.data

    # Add the test URL twice, we will check
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    wait_for_all_checks(client)

    # Add some headers to a request
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "tags": "testtag",
            "fetch_backend": 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests',
            "headers": "xxx:ooo\ncool:yeah\r\n"},
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    with open('test-datastore/headers-testtag.txt', 'w') as f:
        f.write("tag-header: test\r\nurl-header: http://example.com")

    with open('test-datastore/headers.txt', 'w') as f:
        f.write("global-header: nice\r\nnext-global-header: nice\r\nurl-header-global: http://example.com/global")

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))
    with open(f'test-datastore/{uuid}/headers.txt', 'w') as f:
        f.write("watch-header: nice\r\nurl-header-watch: http://example.com/watch")

    wait_for_all_checks(client)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    # Give the thread time to pick it up, this actually is not super reliable and pytest can terminate before the check is ran
    wait_for_all_checks(client)

    # WARNING - pytest and 'wait_for_all_checks' shuts down before it has actually stopped processing when using pyppeteer fetcher
    # so adding more time here
    if os.getenv('FAST_PUPPETEER_CHROME_FETCHER'):
        time.sleep(6)

    res = client.get(url_for("ui.ui_edit.edit_page", uuid="first"))
    assert b"Extra headers file found and will be added to this watch" in res.data

    # Not needed anymore
    os.unlink('test-datastore/headers.txt')
    os.unlink('test-datastore/headers-testtag.txt')

    # The service should echo back the request verb
    res = client.get(
        url_for("ui.ui_views.preview_page", uuid="first"),
        follow_redirects=True
    )

    assert b"Global-Header:nice" in res.data
    assert b"Next-Global-Header:nice" in res.data
    assert b"Xxx:ooo" in res.data
    assert b"Watch-Header:nice" in res.data
    assert b"Tag-Header:test" in res.data
    assert b"Url-Header:http://example.com" in res.data
    assert b"Url-Header-Global:http://example.com/global" in res.data
    assert b"Url-Header-Watch:http://example.com/watch" in res.data

    # Check the custom UA from system settings page made it through
    if os.getenv('PLAYWRIGHT_DRIVER_URL'):
        assert "User-Agent:".encode('utf-8') + webdriver_ua.encode('utf-8') in res.data
    else:
        assert "User-Agent:".encode('utf-8') + requests_ua.encode('utf-8') in res.data

    # unlink headers.txt on start/stop
    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_headers_validation(client, live_server):
    

    test_url = url_for('test_headers', _external=True)
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": 'html_requests',
            "headers": "User-AGent agent-from-watch\r\nsadfsadfsadfsdaf\r\n:foobar"},
        follow_redirects=True
    )

    assert b"Line 1 is missing a &#39;:&#39; separator." in res.data
    assert b"Line 3 has an empty key." in res.data

