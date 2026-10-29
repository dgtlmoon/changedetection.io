import csv
import unittest
from io import StringIO
from types import SimpleNamespace

from changedetectionio.blueprint.watchlist.export import selected_watches_csv


class TestWatchlistExport(unittest.TestCase):
    def test_spreadsheet_formulas_are_text(self):
        for title in ['=1+1', '+cmd', '-cmd', '@SUM(A1)', '  =1+1', '\ttext', '\rtext', '\ntext']:
            with self.subTest(title=title):
                store = SimpleNamespace(data={'watching': {'first': {
                    'url': 'https://example.com', 'title': title, 'last_error': title,
                }}})
                response = selected_watches_csv(store, ['first'])
                rows = list(csv.DictReader(StringIO(response.get_data().decode('utf-8-sig'))))
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
        next(iterator)  # header
        self.assertEqual(lookups, [])
        self.assertIn('https://example.com/first', next(iterator))
        self.assertEqual(lookups, ['first'])
        del watches['second']
        self.assertEqual(list(iterator), [])
