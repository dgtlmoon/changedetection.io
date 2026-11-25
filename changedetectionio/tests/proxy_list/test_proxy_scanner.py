#!/usr/bin/env python3
"""The proxy scanner of a watch ("Check/Scan all" next to the proxy list on its edit page, blueprint/check_proxies):
the watch's page is fetched through every proxy there is, to see which of them get through.

Run by run_proxy_tests.sh against the two squid proxies it starts, with proxies.json-scanner as the proxy list:
those two and one with nothing listening. The page fetched is this test's own server, which the proxies and the
browser reach by this container's hostname, so it can be made to answer 403 for the second scan.
"""
import os
import time

from flask import url_for

from ..util import set_original_response

FETCH_BACKEND = 'html_webdriver' if os.getenv('PLAYWRIGHT_DRIVER_URL') else 'html_requests'


def _start_scan(client, uuid):
    res = client.post(url_for("check_proxies.start_check", uuid=uuid))
    assert res.status_code == 200
    assert set(res.json) >= {'proxy-one', 'proxy-two', 'nothing-listening'}, "Every proxy is being checked"
    return res.json


def _wait_for_scan(client, uuid, timeout=120):
    """The way static/js/recheck-proxy.js waits for it. Returns {proxy key: result}"""
    deadline = time.time() + timeout
    while True:
        res = client.get(url_for("check_proxies.get_recheck_status", uuid=uuid))
        assert res.status_code == 200
        if not any(result['status'] == 'RUNNING' for result in res.json.values()):
            return res.json
        assert time.time() < deadline, f"The scan was still running after {timeout} seconds: {res.json}"
        time.sleep(0.5)


def test_scan_says_which_proxies_get_through_and_scans_again(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    assert {'proxy-one', 'proxy-two', 'nothing-listening'} <= set(datastore.proxy_list), "Run with proxies.json-scanner"

    set_original_response(datastore_path=datastore_path)

    # run_proxy_tests.sh looks for this page in the logs of the two squids, fetched and then refused: the scans
    # really went through each of them
    page = url_for('test_endpoint', _external=True)
    uuid = datastore.add_watch(url=page, extras={'paused': True, 'fetch_backend': FETCH_BACKEND})

    _start_scan(client, uuid)
    results = _wait_for_scan(client, uuid)
    for proxy in ('proxy-one', 'proxy-two'):
        assert results[proxy]['status'] == 'OK', f"{proxy} gets through: {results[proxy]}"
        assert results[proxy]['time'].endswith('s')
    assert results['nothing-listening']['status'].startswith('ERROR'), "A proxy that is not there is an error, not a hang"
    assert results['nothing-listening']['text']

    # The page now refuses everybody. A scan is a new scan every time: until this was tested the results of the
    # first scan were given again for as long as the application ran.
    datastore.data['watching'][uuid]['url'] = f"{page}?status_code=403"
    _start_scan(client, uuid)
    # Asked for again while it is running: the one that is running, not a second one on top
    running = _start_scan(client, uuid)
    assert running['nothing-listening']['status'] == 'RUNNING'

    results = _wait_for_scan(client, uuid)
    for proxy in ('proxy-one', 'proxy-two'):
        assert results[proxy]['status'] == 'ERROR', f"{proxy} is refused now: {results[proxy]}"
        assert '403' in results[proxy]['text'] and 'Access denied' in results[proxy]['text']

    # The scan is for looking, it does not change the watch
    assert not datastore.data['watching'][uuid].get('last_checked')
    assert datastore.data['watching'][uuid].history_n == 0

    # (not delete_all_watches(): it clears the datastore directory, where proxies.json is mounted)
    datastore.delete(uuid)
