import csv
import unittest
import unittest.mock
from io import StringIO
from types import SimpleNamespace

from changedetectionio.blueprint.watchlist.export import _timezone_description, selected_watches_csv


def _lines(response):
    return list(csv.reader(StringIO(response.get_data().decode('utf-8-sig'))))


def _rows(response):
    """Data rows keyed by the column names, which are on the second line (the first is the timezone note)."""
    lines = _lines(response)
    return [dict(zip(lines[1], row)) for row in lines[2:]]


class TestWatchlistExport(unittest.TestCase):
    def test_spreadsheet_formulas_are_text(self):
        for title in ['=1+1', '+cmd', '-cmd', '@SUM(A1)', '  =1+1', '\ttext', '\rtext', '\ntext']:
            with self.subTest(title=title):
                store = SimpleNamespace(data={'watching': {'first': {
                    'url': 'https://example.com', 'title': title, 'last_error': title,
                }}})
                response = selected_watches_csv(store, ['first'])
                rows = _rows(response)
                self.assertEqual(rows[0]['title'], "'" + title)
                self.assertEqual(rows[0]['last_error'], "'" + title)

    def test_rows_are_read_lazily(self):
        lookups = []

        class Watches(dict):
            def get(self, key):
                lookups.append(key)
                return super().get(key)

        watches = Watches(first={'url': 'https://example.com/first'}, second={'url': 'https://example.com/second'})
        response = selected_watches_csv(SimpleNamespace(data={'watching': watches}), ['first', 'second'])
        self.assertEqual(lookups, [])
        iterator = iter(response.response)
        next(iterator)  # BOM
        next(iterator)  # timezone note
        next(iterator)  # header
        self.assertEqual(lookups, [])
        self.assertIn('https://example.com/first', next(iterator))
        self.assertEqual(lookups, ['first'])
        del watches['second']
        self.assertEqual(list(iterator), [])

    def test_dates_are_local_and_the_timezone_is_stated_on_the_first_line(self):
        store = SimpleNamespace(data={
            'settings': {'application': {'scheduler_timezone_default': 'Europe/Prague'}},
            'watching': {'summer': {'url': 'https://example.com/a', 'last_checked': 1750000000},   # 2025-06-15 15:06:40 UTC
                         'winter': {'url': 'https://example.com/b', 'last_checked': 1764000000},   # 2025-11-24 16:00:00 UTC
                         'never': {'url': 'https://example.com/c', 'last_checked': 0}},
        })
        response = selected_watches_csv(store, ['summer', 'winter', 'never'])
        lines = _lines(response)
        # First line: the label in column A and, in column B, the current offset plus the zone name
        self.assertEqual(lines[0][0], 'Timezone of all dates is')
        self.assertRegex(lines[0][1], r'^GMT\+[12] Europe/Prague$')
        self.assertEqual(len(lines[0]), 2)
        self.assertEqual(lines[1], ['url', 'title', 'last_error', 'last_checked', 'in_stock', 'price', 'currency', 'uuid'])
        rows = _rows(response)
        # Local wall-clock time, daylight saving included, and no suffix a spreadsheet would choke on
        self.assertEqual(rows[0]['last_checked'], '2025-06-15 17:06:40')
        self.assertEqual(rows[1]['last_checked'], '2025-11-24 17:00:00')
        self.assertEqual(rows[2]['last_checked'], '')
        for row in rows[:2]:
            self.assertRegex(row['last_checked'], r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')
        self.assertEqual([row['uuid'] for row in rows], ['summer', 'winter', 'never'])

    def test_timezone_falls_back_to_utc(self):
        watching = {'first': {'url': 'https://example.com', 'last_checked': 1750000000}}
        for settings in ({'application': {'scheduler_timezone_default': 'Not/AZone'}}, None):
            with self.subTest(settings=settings):
                data = {'watching': watching}
                if settings is not None:
                    data['settings'] = settings
                with unittest.mock.patch.dict('os.environ', {}, clear=False) as env:
                    env.pop('TZ', None)
                    response = selected_watches_csv(SimpleNamespace(data=data), ['first'])
                    lines = _lines(response)
                self.assertEqual(lines[0], ['Timezone of all dates is', 'GMT+0'])
                self.assertEqual(_rows(response)[0]['last_checked'], '2025-06-15 15:06:40')

    def test_timezone_description(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        cases = [
            ('Europe/Prague', datetime(2026, 7, 1, 12, 0), 'GMT+2 Europe/Prague'),     # summer time
            ('Europe/Prague', datetime(2026, 11, 20, 12, 0), 'GMT+1 Europe/Prague'),   # winter time
            ('America/New_York', datetime(2026, 1, 15, 12, 0), 'GMT-5 America/New_York'),
            ('Asia/Kolkata', datetime(2026, 1, 15, 12, 0), 'GMT+5:30 Asia/Kolkata'),
            ('UTC', datetime(2026, 1, 15, 12, 0), 'GMT+0'),
        ]
        for name, when, expected in cases:
            with self.subTest(name=name, when=when):
                tz = ZoneInfo(name)
                self.assertEqual(_timezone_description(tz, name, now=when.replace(tzinfo=tz)), expected)
