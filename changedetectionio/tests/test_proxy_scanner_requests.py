#!/usr/bin/env python3
"""The proxy scanner's requests (blueprint/check_proxies), without real proxies: what it answers when there is
nothing to scan, and that every scan fetches again. With real proxies: tests/proxy_list/test_proxy_scanner.py."""
import time

from flask import url_for

from changedetectionio.processors.text_json_diff import processor as text_json_diff_processor
from .util import delete_all_watches


def _wait_for_scan(client, uuid):
    for _ in range(100):
        res = client.get(url_for("check_proxies.get_recheck_status", uuid=uuid))
        if res.json and not any(result['status'] == 'RUNNING' for result in res.json.values()):
            return res.json
        time.sleep(0.1)
    raise AssertionError(f"The scan did not finish: {res.json}")


def test_nothing_to_scan(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    assert not datastore.proxy_list

    # No proxies: nothing is scanned (it was an error page, the request had no answer)
    res = client.post(url_for("check_proxies.start_check", uuid=uuid))
    assert res.status_code == 200 and res.json == {}
    assert client.get(url_for("check_proxies.get_recheck_status", uuid=uuid)).json == {}

    # A watch that is not there
    gone = '00000000-0000-4000-8000-000000000000'
    assert client.post(url_for("check_proxies.start_check", uuid=gone)).status_code == 404

    # Starting a scan fetches pages, never by a GET
    assert client.get(url_for("check_proxies.start_check", uuid=uuid)).status_code in (404, 405)

    delete_all_watches(client)


def test_every_scan_fetches_again(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['requests']['extra_proxies'] = [
        {'proxy_name': 'one', 'proxy_url': 'http://127.0.0.1:1'},
        {'proxy_name': 'two', 'proxy_url': 'http://127.0.0.1:2'},
    ]
    try:
        proxies = set(datastore.proxy_list)
        assert len(proxies) >= 2
        uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})

        # No fetching here: note which proxy each fetch was asked to go through
        fetched_through = []

        async def call_browser(self, preferred_proxy_id=None):
            fetched_through.append(preferred_proxy_id)

        monkeypatch.setattr(text_json_diff_processor.perform_site_check, 'call_browser', call_browser)

        res = client.post(url_for("check_proxies.start_check", uuid=uuid))
        assert set(res.json) == proxies
        results = _wait_for_scan(client, uuid)
        assert {result['status'] for result in results.values()} == {'OK'}
        assert sorted(fetched_through) == sorted(proxies), "Once through every proxy"

        # Again: every proxy is fetched through again (the first results used to be given back as they were)
        client.post(url_for("check_proxies.start_check", uuid=uuid))
        _wait_for_scan(client, uuid)
        assert sorted(fetched_through) == sorted(list(proxies) * 2)
    finally:
        datastore.data['settings']['requests']['extra_proxies'] = []

    delete_all_watches(client)
