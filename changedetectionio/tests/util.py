#!/usr/bin/python3


def set_original_response():
    test_return_data = """<html>
    <head><title>head title</title></head>
    <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     </br>
     So let's see what happens.  </br>
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


def live_server_setup(live_server):


    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        # Tried using a global var here but didn't seem to work, so reading from a file instead.
        with open("test-datastore/endpoint-content.txt", "r") as f:
            return f.read()

    @live_server.app.route('/test-endpoint-json')
    def test_endpoint_json():

        from flask import make_response

        with open("test-datastore/endpoint-content.txt", "r") as f:
            resp = make_response(f.read())
            resp.headers['Content-Type'] = 'application/json'
            return resp

    @live_server.app.route('/test-403')
    def test_endpoint_403_error():

        from flask import make_response
        resp = make_response('', 403)
        return resp

    # Just return the headers in the request
    @live_server.app.route('/test-headers')
    def test_headers():

        from flask import request
        output= []

        for header in request.headers:
             output.append("{}:{}".format(str(header[0]),str(header[1])   ))

        return "\n".join(output)

    # Just return the body in the request
    @live_server.app.route('/test-body', methods=['POST', 'GET'])
    def test_body():

        from flask import request

        return request.data

    # Just return the verb in the request
    @live_server.app.route('/test-method', methods=['POST', 'GET', 'PATCH'])
    def test_method():

        from flask import request

        return request.method

    # Where we POST to as a notification
    @live_server.app.route('/test_notification_endpoint', methods=['POST', 'GET'])
    def test_notification_endpoint():
        from flask import request

        with open("test-datastore/notification.txt", "wb") as f:
            # Debug method, dump all POST to file also, used to prove #65
            data = request.stream.read()
            if data != None:
                f.write(data)

        print("\n>> Test notification endpoint was hit.\n")
        return "Text was set"

    live_server.start()
