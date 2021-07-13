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

    with open("test-datastore/output.txt", "w") as f:
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

    with open("test-datastore/output.txt", "w") as f:
        f.write(test_return_data)

    return None


def live_server_setup(live_server):

    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        # Tried using a global var here but didn't seem to work, so reading from a file instead.
        with open("test-datastore/output.txt", "r") as f:
            return f.read()

    # Where we POST to as a notification
    @live_server.app.route('/test_notification_endpoint', methods=['POST'])
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
