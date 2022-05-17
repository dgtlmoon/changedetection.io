#!/usr/bin/python3

from flask import make_response, request

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


def live_server_setup(live_server):

    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        ctype = request.args.get('content_type')
        status_code = request.args.get('status_code')

        try:
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

    live_server.start()
