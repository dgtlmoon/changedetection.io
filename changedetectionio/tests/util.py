#!/usr/bin/env python3
from operator import truediv

from flask import make_response, request, current_app
from flask import url_for
import logging
import time
import os
import threading

# Thread-safe global storage for test endpoint content
# Avoids filesystem cache issues in parallel tests
_test_endpoint_content_lock = threading.Lock()
_test_endpoint_content = {}

def write_test_file_and_sync(filepath, content, mode='w'):
    """
    Write test data to file and ensure it's synced to disk.
    Also stores in thread-safe global dict to bypass filesystem cache.

    Critical for parallel tests where workers may read files immediately after write.
    Without fsync(), data may still be in OS buffers when workers try to read,
    causing race conditions where old data is seen.

    Args:
        filepath: Full path to file
        content: Content to write (str or bytes)
        mode: File mode ('w' for text, 'wb' for binary)
    """
    # Convert content to bytes if needed
    if isinstance(content, str):
        content_bytes = content.encode('utf-8')
    else:
        content_bytes = content

    # Store in thread-safe global dict for instant access
    with _test_endpoint_content_lock:
        _test_endpoint_content[os.path.basename(filepath)] = content_bytes

    # Also write to file for compatibility
    with open(filepath, mode) as f:
        f.write(content)
        f.flush()  # Flush Python buffer to OS
        os.fsync(f.fileno())  # Force OS to write to disk

def set_original_response(datastore_path, extra_title=''):
    test_return_data = f"""<html>
    <head><title>head title{extra_title}</title></head>
    <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
     <span class="foobar-detection" style='display:none'></span>
     </body>
     </html>
    """

    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), test_return_data)
    return None

def set_modified_response(datastore_path):
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

    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), test_return_data)
    return None
def set_longer_modified_response(datastore_path):
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

    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), test_return_data)
    return None

def set_more_modified_response(datastore_path):
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

    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), test_return_data)
    return None


def set_empty_text_response(datastore_path):
    test_return_data = """<html><body></body></html>"""

    write_test_file_and_sync(os.path.join(datastore_path, "endpoint-content.txt"), test_return_data)

    return None

def wait_for_notification_endpoint_output(datastore_path):
    '''Apprise can take a few seconds to fire'''
    #@todo - could check the apprise object directly instead of looking for this file
    from os.path import isfile
    notification_file = os.path.join(datastore_path, "notification.txt")
    for i in range(1, 20):
        time.sleep(1)
        if isfile(notification_file):
            return True

    return False

# kinda funky, but works for now
def get_UUID_for_tag_name(client, name):
    app_config = client.application.config.get('DATASTORE').data
    for uuid, tag in app_config['settings']['application'].get('tags', {}).items():
        if name == tag.get('title', '').lower().strip():
            return uuid
    return None


# kinda funky, but works for now
def extract_rss_token_from_UI(client):
    return client.application.config.get('DATASTORE').data['settings']['application'].get('rss_access_token')
#    import re
#    res = client.get(
#        url_for("watchlist.index"),
#    )
#    m = re.search('token=(.+?)"', str(res.data))
#    token_key = m.group(1)
#    return token_key.strip()

# kinda funky, but works for now
def extract_UUID_from_client(client):
    import re
    res = client.get(
        url_for("watchlist.index"),
    )
    # <span id="api-key">{{api_key}}</span>

    m = re.search('edit/(.+?)[#"]', str(res.data))
    uuid = m.group(1)
    return uuid.strip()

def delete_all_watches(client=None):
    wait_for_all_checks(client)

    uuids = list(client.application.config.get('DATASTORE').data['watching'])
    for uuid in uuids:
        client.application.config.get('DATASTORE').delete(uuid)
    from changedetectionio.flask_app import update_q

    # Clear the queue to prevent leakage to next test
    # Use clear() method to ensure both priority_items and notification_queue are drained
    if hasattr(update_q, 'clear'):
        update_q.clear()
    else:
        # Fallback for old implementation
        while not update_q.empty():
            try:
                update_q.get_nowait()
            except:
                break

    time.sleep(0.2)

    # Delete any old watch metadata
    from pathlib import Path
    for file in Path(client.application.config.get('DATASTORE').datastore_path).rglob("*.json"):
        file.unlink()


def wait_for_all_checks(client=None):
    """
    Waits until the queue is empty and workers are idle.
    Delegates to worker_pool.wait_for_all_checks for shared logic.
    """
    from changedetectionio.flask_app import update_q as global_update_q
    from changedetectionio import worker_pool
    return worker_pool.wait_for_all_checks(global_update_q, timeout=150)


def wait_for_watch_history(client, min_history_count=2, timeout=10):
    """
    Wait for watches to have sufficient history entries.
    Useful after wait_for_all_checks() when you need to ensure history is populated.

    Args:
        client: Test client with access to datastore
        min_history_count: Minimum number of history entries required
        timeout: Maximum time to wait in seconds
    """
    datastore = client.application.config.get('DATASTORE')
    start_time = time.time()

    while time.time() - start_time < timeout:
        all_have_history = True
        for uuid, watch in datastore.data['watching'].items():
            history_count = len(watch.history.keys())
            if history_count < min_history_count:
                all_have_history = False
                break

        if all_have_history:
            return True

        time.sleep(0.2)

    # Timeout - return False
    return False


# Replaced by new_live_server_setup and calling per function scope in conftest.py
def  live_server_setup(live_server):
    return True

def new_live_server_setup(live_server):

    @live_server.app.route('/test-random-content-endpoint')
    def test_random_content_endpoint():
        import secrets
        return "Random content - {}\n".format(secrets.token_hex(64))

    @live_server.app.route('/test-endpoint2')
    def test_endpoint2():
        return "<html><body>some basic content</body></html>"

    @live_server.app.route('/test-endpoint')
    def test_endpoint():
        # REMOVED: logger.debug() causes file locking between test process and Flask server process
        # Flask server runs in separate multiprocessing.Process and inherited loguru tries to
        # write to same log files, causing request handlers to block on file locks
        # from loguru import logger
        # logger.debug(f"/test-endpoint hit {request}")
        ctype = request.args.get('content_type')
        status_code = request.args.get('status_code')
        content = request.args.get('content') or None
        delay = int(request.args.get('delay', 0))

        if delay:
            time.sleep(delay)

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

            # Check thread-safe global dict first (instant, no cache issues)
            # Fall back to file if not in dict (for tests that write directly)
            with _test_endpoint_content_lock:
                content_data = _test_endpoint_content.get("endpoint-content.txt")

            if content_data is None:
                # Not in global dict, read from file
                datastore_path = current_app.config.get('TEST_DATASTORE_PATH', 'test-datastore')
                filepath = os.path.join(datastore_path, "endpoint-content.txt")

                # REMOVED: os.sync() was blocking for many seconds during parallel tests
                # With -n 6+ parallel tests, heavy I/O causes os.sync() to wait for ALL
                # system writes to complete, causing "Read timed out" errors
                # File writes from test code are already flushed by the time workers fetch

                try:
                    with open(filepath, "rb") as f:
                        content_data = f.read()
                except Exception as e:
                    # REMOVED: logger.error() causes file locking in multiprocess context
                    # Just raise the exception directly for debugging
                    raise

            resp = make_response(content_data, status_code)
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
    @live_server.app.route('/test_notification_endpoint', methods=['POST', 'GET'])
    def test_notification_endpoint():
        datastore_path = current_app.config.get('TEST_DATASTORE_PATH', 'test-datastore')

        with open(os.path.join(datastore_path, "notification.txt"), "wb") as f:
            # Debug method, dump all POST to file also, used to prove #65
            data = request.stream.read()
            if data != None:
                f.write(data)

        with open(os.path.join(datastore_path, "notification-url.txt"), "w") as f:
            f.write(request.url)

        with open(os.path.join(datastore_path, "notification-headers.txt"), "w") as f:
            f.write(str(request.headers))

        if request.content_type:
            with open(os.path.join(datastore_path, "notification-content-type.txt"), "w") as f:
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
        datastore_path = current_app.config.get('TEST_DATASTORE_PATH', 'test-datastore')

        # Force filesystem sync before reading to ensure fresh data
        try:
            os.sync()
        except (AttributeError, PermissionError):
            pass

        # Tried using a global var here but didn't seem to work, so reading from a file instead.
        with open(os.path.join(datastore_path, "endpoint-test.pdf"), "rb") as f:
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
                <button name="test-button" onclick="
                getElementById('remove').remove();
                getElementById('some-content').innerHTML = atob('SSBzbWVsbCBKYXZhU2NyaXB0IGJlY2F1c2UgdGhlIGJ1dHRvbiB3YXMgcHJlc3NlZCE=');
                getElementById('reflect-text').innerHTML = getElementById('test-input-text').value;
                ">Click here</button>
                
                <div id="some-content"></div>
                
                <pre>
                {header_text.lower()}
                </pre>
                
                <br>
                <!-- used for testing that the jinja2 compiled here --->
                <input type="text" value="" id="test-input-text" /><br>
                <div id="reflect-text">Waiting to reflect text from #test-input-text here</div>
              </form>
                
           </body>
         </html>""", 200)
        resp.headers['Content-Type'] = 'text/html'
        return resp

    live_server.start()
