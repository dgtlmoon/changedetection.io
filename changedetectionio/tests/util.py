#!/usr/bin/env python3

from flask import make_response, request
from flask import url_for
import logging
import time

def set_original_response():
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

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)
    return None

def set_modified_response():
    test_return_data = """<html>
    <head><title>modified head title</title></head>
    <body>
     Some initial text<br>
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None
def set_longer_modified_response():
    test_return_data = """<html>
    <head><title>modified head title</title></head>
    <body>
     Some initial text<br>
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     So let's see what happens.  <br>
      So let's see what happens.  <br>
     So let's see what happens.  <br>           
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None
def set_more_modified_response():
    test_return_data = """<html>
    <head><title>modified head title</title></head>
    <body>
     Some initial text<br>
     <p>which has this one new line</p>
     <br>
     So let's see what happens.  <br>
     Ohh yeah awesome<br>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None


def set_empty_text_response():
    test_return_data = """<html><body></body></html>"""

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None

def wait_for_notification_endpoint_output():
    '''Apprise can take a few seconds to fire'''
    #@todo - could check the apprise object directly instead of looking for this file
    from os.path import isfile
    for i in range(1, 20):
        time.sleep(1)
        if isfile("test-datastore/notification.txt"):
            return True

    return False


# kinda funky, but works for now
def extract_api_key_from_UI(client):
    import re
    res = client.get(
        url_for("settings_page"),
    )
    # <span id="api-key">{{api_key}}</span>

    m = re.search('<span id="api-key">(.+?)</span>', str(res.data))
    api_key = m.group(1)
    return api_key.strip()


# kinda funky, but works for now
def get_UUID_for_tag_name(client, name):
    app_config = client.application.config.get('DATASTORE').data
    for uuid, tag in app_config['settings']['application'].get('tags', {}).items():
        if name == tag.get('title', '').lower().strip():
            return uuid
    return None


# kinda funky, but works for now
def extract_rss_token_from_UI(client):
    import re
    res = client.get(
        url_for("index"),
    )
    m = re.search('token=(.+?)"', str(res.data))
    token_key = m.group(1)
    return token_key.strip()

# kinda funky, but works for now
def extract_UUID_from_client(client):
    import re
    res = client.get(
        url_for("index"),
    )
    # <span id="api-key">{{api_key}}</span>

    m = re.search('edit/(.+?)[#"]', str(res.data))
    uuid = m.group(1)
    return uuid.strip()

def wait_for_all_checks(client):
    # actually this is not entirely true, it can still be 'processing' but not in the queue
    # Loop waiting until done..
    attempt=0
    # because sub-second rechecks are problematic in testing, use lots of delays
    time.sleep(1)
    while attempt < 60:
        res = client.get(url_for("index"))
        if not b'Checking now' in res.data:
            break
        logging.getLogger().info("Waiting for watch-list to not say 'Checking now'.. {}".format(attempt))
        time.sleep(1)
        attempt += 1

    time.sleep(1)

def live_server_setup(live_server):

    @live_server.app.route('/test-random-content-endpoint')
    def test_random_content_endpoint():
        import secrets
        return "Random content - {}\n".format(secrets.token_hex(64))

    @live_server.app.route('/test-endpoint2')
    def test_endpoint2():
        return "<html><body>some basic content</body></html>"

    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        ctype = request.args.get('content_type')
        status_code = request.args.get('status_code')
        content = request.args.get('content') or None

        # Used to just try to break the header detection
        uppercase_headers = request.args.get('uppercase_headers')

        try:
            if content is not None:
                resp = make_response(content, status_code)
                if uppercase_headers:
                    ctype=ctype.upper()
                    resp.headers['CONTENT-TYPE'] = ctype if ctype else 'text/html'
                else:
                    resp.headers['Content-Type'] = ctype if ctype else 'text/html'
                return resp

            # Tried using a global var here but didn't seem to work, so reading from a file instead.
            with open("test-datastore/endpoint-content.txt", "r") as f:
                resp = make_response(f.read(), status_code)
                if uppercase_headers:
                    resp.headers['CONTENT-TYPE'] = ctype if ctype else 'text/html'
                else:
                    resp.headers['Content-Type'] = ctype if ctype else 'text/html'
                return resp
        except FileNotFoundError:
            return make_response('', status_code)

    # Just return the headers in the request
    @live_server.app.route('/test-headers')
    def test_headers():

        output = []

        for header in request.headers:
            output.append("{}:{}".format(str(header[0]), str(header[1])))

        content = "\n".join(output)

        resp = make_response(content, 200)
        resp.headers['server'] = 'custom'
        return resp

    # Just return the body in the request
    @live_server.app.route('/test-body', methods=['POST', 'GET'])
    def test_body():
        print ("TEST-BODY GOT", request.data, "returning")
        return request.data

    # Just return the verb in the request
    @live_server.app.route('/test-method', methods=['POST', 'GET', 'PATCH'])
    def test_method():
        return request.method

    # Where we POST to as a notification, also use a space here to test URL escaping is OK across all tests that use this. ( #2868 )
    @live_server.app.route('/test_notification endpoint', methods=['POST', 'GET'])
    def test_notification_endpoint():

        with open("test-datastore/notification.txt", "wb") as f:
            # Debug method, dump all POST to file also, used to prove #65
            data = request.stream.read()
            if data != None:
                f.write(data)

        with open("test-datastore/notification-url.txt", "w") as f:
            f.write(request.url)

        with open("test-datastore/notification-headers.txt", "w") as f:
            f.write(str(request.headers))

        if request.content_type:
            with open("test-datastore/notification-content-type.txt", "w") as f:
                f.write(request.content_type)

        print("\n>> Test notification endpoint was hit.\n", data)

        content = "Text was set"
        status_code = request.args.get('status_code',200)
        resp = make_response(content, status_code)
        return resp

    # Just return the verb in the request
    @live_server.app.route('/test-basicauth', methods=['GET'])
    def test_basicauth_method():
        auth = request.authorization
        ret = " ".join([auth.username, auth.password, auth.type])
        return ret

    # Just return some GET var
    @live_server.app.route('/test-return-query', methods=['GET'])
    def test_return_query():
        return request.query_string


    @live_server.app.route('/endpoint-test.pdf')
    def test_pdf_endpoint():

        # Tried using a global var here but didn't seem to work, so reading from a file instead.
        with open("test-datastore/endpoint-test.pdf", "rb") as f:
            resp = make_response(f.read(), 200)
            resp.headers['Content-Type'] = 'application/pdf'
            return resp

    @live_server.app.route('/test-interactive-html-endpoint')
    def test_interactive_html_endpoint():
        header_text=""
        for k,v in request.headers.items():
            header_text += f"{k}: {v}<br>"

        resp = make_response(f"""
        <html>
          <body>
          Primitive JS check for <pre>changedetectionio/tests/visualselector/test_fetch_data.py</pre>
            <p id="remove">This text should be removed</p>
              <form onsubmit="event.preventDefault();">
            <!-- obfuscated text so that we dont accidentally get a false positive due to conversion of the source :) --->
                <button name="test-button" onclick="getElementById('remove').remove();getElementById('some-content').innerHTML = atob('SSBzbWVsbCBKYXZhU2NyaXB0IGJlY2F1c2UgdGhlIGJ1dHRvbiB3YXMgcHJlc3NlZCE=')">Click here</button>
                <div id=some-content></div>
                <pre>
                {header_text.lower()}
                </pre>
              </body>
         </html>""", 200)
        resp.headers['Content-Type'] = 'text/html'
        return resp

    live_server.start()

