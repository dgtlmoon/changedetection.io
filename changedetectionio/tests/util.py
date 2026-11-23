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

def import_example_plugin(example_dir, package):
    """Import an example_plugins/<example_dir> package as its own top-level package, the way
    `pip install .` makes it importable, e.g. import_example_plugin('processor/wordcounter', 'cdio_example_wordcounter')"""
    import importlib
    import sys
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'example_plugins', example_dir))
    sys.path.insert(0, path)
    try:
        return importlib.import_module(package)
    finally:
        sys.path.remove(path)


def clear_plugin_discovery_caches():
    """Processor discovery and the merged API spec are cached at first use, a plugin registered
    afterwards (like in a test) is only seen once these are cleared."""
    from changedetectionio import processors, api
    for f in (processors.find_processors, processors.get_plugin_processor_metadata, processors._available_processors_cached,
              api.build_merged_spec_dict, api.get_openapi_spec, api.get_openapi_schema_dict,
              api._resolve_schema_properties, api.get_watch_schema_properties, api.get_tag_schema_properties):
        f.cache_clear()


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


def get_form_field(html, name):
    """Return the <input>, <select> or <textarea> named `name` in the page, or None.

    Use this to assert a field's value (field['value'], field.has_attr('checked')) instead of matching raw
    bytes like b'type="text" value="5"', which breaks on attribute order, quoting or a changed input type
    (WTForms 3.3 renders FloatField as type="number"). Keep raw byte checks where the escaping is the point.
    """
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, 'html.parser').find(['input', 'select', 'textarea'], attrs={'name': name})

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

    base_path = Path(
        client.application.config.get('DATASTORE').datastore_path
    ).resolve()

    max_depth = 2

    for file in base_path.rglob("*.json"):
        # Calculate depth relative to base path
        depth = len(file.relative_to(base_path).parts) - 1

        if depth <= max_depth and file.is_file():
            file.unlink()


def wait_for_all_checks(client=None):
    """
    Waits until the queue is empty and workers are idle.
    Delegates to worker_pool.wait_for_all_checks for shared logic.
    """
    from changedetectionio.flask_app import update_q as global_update_q
    from changedetectionio import worker_pool
    done = worker_pool.wait_for_all_checks(global_update_q, timeout=150)
    if client is None:
        return done

    # A monitor that was just added (an import, the API) isn't queued by that request, the scheduler finds it on its
    # next pass, up to a second later. Until then the queue is empty and the workers idle, so the wait above can return
    # before its first check has even started, and the test changes the page under it. Wait for the scheduler to pick
    # up every unpaused monitor that was never checked, a few seconds at most (a time schedule may keep one waiting).
    datastore = client.application.config.get('DATASTORE')
    if not datastore or datastore.data['settings']['application'].get('all_paused'):
        return done
    deadline = time.time() + 5
    while time.time() < deadline:
        unchecked = [w for w in list(datastore.data['watching'].values())
                     if not w.get('paused') and not w.get('last_checked')]
        if not unchecked:
            break
        time.sleep(0.2)
    else:
        return done
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


def fetch_llm_summary(client, url, timeout=15):
    """Drive the /llm-summary start-then-poll flow the way static/js/llm-summary.js does.

    Generation runs on a background thread now, so a single request can only ever return
    202 "pending". POST starts it (and answers straight away when the summary is already cached),
    then the GET poll is read-only. Returns the final response.
    """
    res = client.post(url)
    if res.status_code != 202:
        return res

    deadline = time.time() + timeout
    while time.time() < deadline:
        res = client.get(url)
        if res.status_code != 202 and (res.get_json() or {}).get('status') != 'pending':
            return res
        time.sleep(0.05)

    raise AssertionError(f"LLM summary at {url} still pending after {timeout}s")


# Replaced by new_live_server_setup and calling per function scope in conftest.py
def  live_server_setup(live_server):
    return True

def new_live_server_setup(live_server):

    @live_server.app.route('/test-random-content-endpoint')
    def test_random_content_endpoint():
        import secrets
        return "Random content - {}\n".format(secrets.token_hex(64))

    # Re-navigation gate: the first hit answers with an error status AND a client-side meta
    # refresh, the second serves the real page. This mirrors sites that gate visitors they have
    # not seen recently (reported against fotokoch.de, which answers 503 + meta refresh and then
    # serves a 200). The browser follows the refresh, so the fetch has to be judged on the
    # document we actually end up extracting rather than on the interstitial.
    # What a parked domain serves: an empty document that sends the browser on from its load event
    @live_server.app.route('/test-onload-redirect')
    def test_onload_redirect():
        landing = url_for('test_onload_redirect_landing')
        return ('<!DOCTYPE html><html><head><script>window.onload=function(){window.location.href="'
                + landing + '"}</script></head></html>')

    @live_server.app.route('/test-onload-redirect-landing')
    def test_onload_redirect_landing():
        return '<html><body><h1>This domain is for sale</h1></body></html>'

    # Keyed on last-seen time rather than a hit count, so EVERY fresh check starts out gated -
    # a counter would serve a clean 200 to the second check and let the test pass without the fix.
    _interstitial_last_seen = {}

    @live_server.app.route('/test-interstitial')
    def test_interstitial():
        key = request.args.get('key', 'default')
        now = time.time()
        seen_recently = (now - _interstitial_last_seen.get(key, 0)) < 10
        _interstitial_last_seen[key] = now
        if not seen_recently:
            resp = make_response(
                '<html><head><meta http-equiv="refresh" content="1"></head>'
                '<body>Browser check in progress, you will be redirected</body></html>', 503)
        else:
            resp = make_response(
                '<html><body><h1>The real page content is here</h1></body></html>', 200)
        resp.headers['Content-Type'] = 'text/html'
        return resp

    # A page whose icon the browser may load for itself, but page script may not read - what a browser
    # that enforces cross-origin rules does with an icon on another host. Told apart by the Accept
    # header: the browser's own icon request asks for images ('image/avif,image/webp,...'), a fetch()
    # from page script asks for '*/*'. (Sec-Fetch-Dest would say it too, but is not sent over plain http)
    @live_server.app.route('/test-favicon-page')
    def test_favicon_page():
        icon = url_for('test_favicon_browser_only', key=request.args.get('key', 'default'))
        return (f'<html><head><title>favicon</title><link rel="icon" type="image/png" href="{icon}"></head>'
                f'<body>A page with an icon only the browser itself may fetch</body></html>')

    # A page that never leaves the browser's main thread alone for long, the way an animation drawn
    # without a GPU does: anything the fetcher asks the page has to wait for a gap. Its icon is one
    # only the browser itself may fetch.
    @live_server.app.route('/test-busy-page')
    def test_busy_page():
        icon = url_for('test_favicon_browser_only', key=request.args.get('key', 'default'))
        return (f'<html><head><title>busy</title><link rel="icon" type="image/png" href="{icon}"></head>'
                '<body><p>The busy page text is here</p><script>'
                # On an interval so that stopping the script that is running does not end it, the next one starts
                'setInterval(() => { const until = performance.now() + 8000; while (performance.now() < until) {} }, 0);'
                '</script></body></html>')

    _favicon_requests = {}

    @live_server.app.route('/test-favicon-browser-only.png')
    def test_favicon_browser_only():
        import base64
        by = 'browser' if request.headers.get('Accept', '').startswith('image/') else 'script'
        _favicon_requests.setdefault(request.args.get('key', 'default'), []).append(by)
        if by != 'browser':
            return make_response('Not for scripts', 403)
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')
        resp = make_response(png, 200)
        resp.headers['Content-Type'] = 'image/png'
        return resp

    @live_server.app.route('/test-favicon-requests')
    def test_favicon_requests():
        return {'requested_by': _favicon_requests.get(request.args.get('key', 'default'), [])}

    # A tall page that never stops animating, with the things a taller viewport or a scroll changes:
    # a hero the height of the viewport (green), a fixed header (blue) and a band far down (magenta).
    # And three canvases: a very large one on the first screen (cyan), a very large one below it
    # (red) and one the size of a graph far down (orange).
    @live_server.app.route('/test-animated-tall-page')
    def test_animated_tall_page():
        return """<html><head><style>
            body { margin: 0; height: 15000px; }
            #hero, #header, #far-down { left: 0; width: 100%; }
            #hero { position: absolute; top: 0; height: 100vh; background: rgb(0, 160, 0); }
            #header { position: fixed; top: 0; height: 40px; background: rgb(0, 0, 255); }
            #far-down { position: absolute; top: 12000px; height: 400px; background: rgb(255, 0, 255); }
            p { position: absolute; top: 110vh; }
            canvas { position: absolute; left: 0; width: 100%; height: 200px; }
        </style></head><body>
        <div id="hero"></div><div id="header"></div><div id="far-down"></div>
        <p>The animated page text is here</p>
        <canvas id="large-first-screen" width="3000" height="2000" style="top: 100px"></canvas>
        <canvas id="large-below" width="3000" height="2000" style="top: 6000px"></canvas>
        <canvas id="graph" width="600" height="300" style="top: 13000px"></canvas>
        <script>
            for (const [id, colour] of [['large-first-screen', 'rgb(0, 255, 255)'], ['large-below', 'rgb(255, 0, 0)'], ['graph', 'rgb(255, 165, 0)']]) {
                const canvas = document.getElementById(id), context = canvas.getContext('2d');
                context.fillStyle = colour;
                context.fillRect(0, 0, canvas.width, canvas.height);
            }
            // Keeps the renderer busy on every frame, the way a large animation does
            (function animate() {
                const until = performance.now() + 30;
                while (performance.now() < until) {}
                requestAnimationFrame(animate);
            })();
        </script></body></html>"""

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

    # A stand-in scraping API with the JSON contract of example_plugins/fetcher/fallback_fetcher
    @live_server.app.route('/test-scrape-api', methods=['POST'])
    def test_scrape_api():
        body = request.get_json()
        one_pixel_png = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
        return {
            'status_code': int(request.args.get('status_code', 200)),
            'content': f"<html><body><p>Fetched by the scraping API</p><p>url:{body.get('url')}</p>"
                       f"<p>key:{request.headers.get('X-Api-Key')}</p></body></html>",
            'content_type': 'text/html',
            'screenshot': one_pixel_png if body.get('screenshot') else None,
        }


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


def new_mcp_token(client, name='test', tags=None, **permissions):
    """A new MCP access token (blueprint/mcp/tokens.py), every row at write unless given, e.g. notifications='read'.
    tags: the tag uuids it's limited to, None for every monitor."""
    from changedetectionio.blueprint.mcp.tokens import add_token
    settings = client.application.config['DATASTORE'].data['settings']['application']
    levels = {'monitors': 'write', 'tags': 'write', 'notifications': 'write', 'browser': 'write', 'system': 'read', **permissions}
    return add_token(settings, name, levels, tags)[1]
