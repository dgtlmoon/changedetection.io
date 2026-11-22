#!/usr/bin/env python3
"""#4607: paused watches must not be reported in /api/v1/systeminfo `overdue_watches`.

Tests the rule directly, with fixed times: against the live app the scheduler checks an overdue watch straight
away, which made the watch not overdue any more by the time the API was asked (a race seen in CI).
"""
from changedetectionio.api.SystemInfo import overdue_watch_uuids

NOW = 1700000000


class FakeWatch(dict):
    def threshold_seconds(self):
        return self.get('interval')


class FakeDatastore:
    threshold_seconds = 3 * 3600  # the system wide default

    def __init__(self, watches, all_paused=False):
        self.data = {'watching': watches, 'settings': {'application': {'all_paused': all_paused}}}


def _watches():
    hour_ago = NOW - 3600
    return {
        # 1 minute interval, last checked an hour ago: well past the interval plus the 5 minute grace
        'active': FakeWatch(interval=60, last_checked=hour_ago),
        'paused': FakeWatch(interval=60, last_checked=hour_ago, paused=True),
        # Just checked
        'fresh': FakeWatch(interval=60, last_checked=NOW - 10),
        # Within the 5 minute grace
        'grace': FakeWatch(interval=60, last_checked=NOW - 200),
        # No own interval: the 3 hour system default applies
        'default': FakeWatch(interval=None, last_checked=hour_ago),
        # Never checked
        'never': FakeWatch(interval=60, last_checked=0),
    }


def test_overdue_skips_paused():
    assert sorted(overdue_watch_uuids(FakeDatastore(_watches()), now=NOW)) == ['active', 'never']


def test_overdue_nothing_while_all_paused():
    assert overdue_watch_uuids(FakeDatastore(_watches(), all_paused=True), now=NOW) == []
