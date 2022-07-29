#!/usr/bin/python3

from flask import make_response, request
from flask import url_for
from werkzeug import Request
import io

import multiprocessing
multiprocessing.set_start_method("fork")

def set_original_response():
    test_return_data = """<html>
    <head><title>head title</title></head>
    <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
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
     Some initial text</br>
     <p>which has this one new line</p>
     </br>
     So let's see what happens.  </br>
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
     Some initial text</br>
     <p>which has this one new line</p>
     </br>
     So let's see what happens.  </br>
     Ohh yeah awesome<br/>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

    return None


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

def live_server_setup(live_server):

    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        ctype = request.args.get('content_type')
        status_code = request.args.get('status_code')
        content = request.args.get('content') or None

        try:
            if content is not None:
                resp = make_response(content, status_code)
                resp.headers['Content-Type'] = ctype if ctype else 'text/html'
                return resp

            # Tried using a global var here but didn't seem to work, so reading from a file instead.
            with open("test-datastore/endpoint-content.txt", "r") as f:
                resp = make_response(f.read(), status_code)
                resp.headers['Content-Type'] = ctype if ctype else 'text/html'
                return resp
        except FileNotFoundError:
            return make_response('', status_code)

    # Just return the headers in the request
    @live_server.app.route('/test-headers')
    def test_headers():

        output= []

        for header in request.headers:
             output.append("{}:{}".format(str(header[0]),str(header[1])   ))

        return "\n".join(output)

    # Just return the body in the request
    @live_server.app.route('/test-body', methods=['POST', 'GET'])
    def test_body():
        print ("TEST-BODY GOT", request.data, "returning")
        return request.data

    # Just return the verb in the request
    @live_server.app.route('/test-method', methods=['POST', 'GET', 'PATCH'])
    def test_method():
        return request.method

    # Where we POST to as a notification
    @live_server.app.route('/test_notification_endpoint', methods=['POST', 'GET'])
    def test_notification_endpoint():
        with open("test-datastore/notification.txt", "wb") as f:
            # Debug method, dump all POST to file also, used to prove #65
            data = request.stream.read()
            if data != None:
                f.write(data)

        print("\n>> Test notification endpoint was hit.\n", data)
        return "Text was set"


    # Just return the verb in the request
    @live_server.app.route('/test-basicauth', methods=['GET'])
    def test_basicauth_method():
        auth = request.authorization
        ret = " ".join([auth.username, auth.password, auth.type])
        return ret

    # Make sure any checkboxes that are supposed to be defaulted to true are set during the post request
    # This is due to the fact that defaults are set in the HTML which we are not using during tests.
    # This does not affect the server when running outside of a test
    class DefaultCheckboxMiddleware(object):
        def __init__(self, app):
            self.app = app

        def __call__(self, environ, start_response):
            request = Request(environ)
            if request.method == "POST" and "/edit" in request.path:
                body = environ['wsgi.input'].read()

                # if the checkboxes are not set, set them to true
                if b"trigger_add" not in body:
                    body += b'&trigger_add=y'

                if b"trigger_del" not in body:
                    body += b'&trigger_del=y'

                # remove any checkboxes set to "n" so wtforms processes them correctly
                body = body.replace(b"trigger_add=n", b"")
                body = body.replace(b"trigger_del=n", b"")
                body = body.replace(b"&&", b"&")

                new_stream = io.BytesIO(body)
                environ["CONTENT_LENGTH"] = len(body)
                environ['wsgi.input'] = new_stream

            return self.app(environ, start_response)

    live_server.app.wsgi_app = DefaultCheckboxMiddleware(live_server.app.wsgi_app)
    live_server.start()
