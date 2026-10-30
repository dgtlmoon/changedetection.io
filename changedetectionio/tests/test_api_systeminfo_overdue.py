#!/usr/bin/env python3
"""#4607: paused watches must not be reported in /api/v1/systeminfo `overdue_watches`."""
import time

from flask import url_for

from .util import delete_all_watches


def test_systeminfo_overdue_skips_paused(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config['DATASTORE']
    settings = datastore.data['settings']['application']
    api_key = settings.get('api_access_token')

    def watch(url, paused):
        # A 1 minute interval, last checked an hour ago: well past the interval plus the 5 minute grace
        uuid = datastore.add_watch(url=url, extras={'paused': paused, 'time_between_check_use_default': False,
                                                    'time_between_check': {'minutes': 1}})
        datastore.data['watching'][uuid]['last_checked'] = int(time.time()) - 3600
        return uuid

    active = watch('https://example.com/active', paused=False)
    paused = watch('https://example.com/paused', paused=True)

    def overdue():
        res = client.get(url_for('systeminfo'), headers={'x-api-key': api_key})
        assert res.status_code == 200
        return res.json['overdue_watches']

    assert active in overdue()
    assert paused not in overdue()

    # "Pause all": nothing is supposed to be checked, so nothing is overdue
    settings['all_paused'] = True
    try:
        assert overdue() == []
    finally:
        settings['all_paused'] = False

    delete_all_watches(client)
