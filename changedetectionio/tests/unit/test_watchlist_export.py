import csv
import unittest
import unittest.mock
from io import StringIO
from types import SimpleNamespace

from changedetectionio.blueprint.watchlist.export import selected_watches_csv


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
        # Column A of the first line names the timezone, and that line has no other cell
        self.assertEqual(lines[0], ['All dates are in timezone Europe/Prague'])
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
                self.assertEqual(lines[0], ['All dates are in timezone UTC'])
                self.assertEqual(_rows(response)[0]['last_checked'], '2025-06-15 15:06:40')
