#!/usr/bin/env python3
"""
Regression: the watch-list "deal" filter must not crash when a watch's `restock` field is a
plain dict rather than a Restock object.

The built-in extruct path stores a Restock, but plugin fallbacks (notably the LLM restock
scraper) store a plain dict. watch_is_deal() then called dict.get_price_change_percent() ->
AttributeError -> 500 on the whole watch-list page.

Run from the tests/ directory:
    python -m unittest unit/test_restock_deal_filter.py
"""
import shutil
import tempfile
import time
import unittest

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.blueprint.watchlist.filters import watch_is_deal


class TestRestockDealFilter(unittest.TestCase):
    def setUp(self):
        self.test_datastore_path = tempfile.mkdtemp()
        self.store = ChangeDetectionStore(
            datastore_path=self.test_datastore_path,
            include_default_watches=False,
        )

    def tearDown(self):
        self.store.stop_thread = True
        time.sleep(0.5)
        shutil.rmtree(self.test_datastore_path, ignore_errors=True)

    def _restock_watch(self):
        uuid = self.store.add_watch(url='https://example.com', extras={'processor': 'restock_diff'})
        return self.store.data['watching'][uuid]

    def test_plain_dict_restock_price_drop_is_a_deal(self):
        watch = self._restock_watch()
        # Force a *plain dict* (bypassing the model's Restock rehydration), exactly as the LLM
        # restock fallback plugin leaves it.
        dict.__setitem__(watch, 'restock', {'in_stock': True, 'price': 80.0, 'last_price': 100.0, 'currency': 'USD'})
        self.assertFalse(hasattr(watch['restock'], 'get_price_change_percent'))  # really a plain dict

        # Must not raise AttributeError, and a 20% drop is a deal.
        self.assertTrue(watch_is_deal(watch))

    def test_plain_dict_restock_price_rise_is_not_a_deal(self):
        watch = self._restock_watch()
        dict.__setitem__(watch, 'restock', {'in_stock': True, 'price': 120.0, 'last_price': 100.0})
        self.assertFalse(watch_is_deal(watch))

    def test_restock_object_still_works(self):
        from changedetectionio.processors.restock_diff import Restock
        watch = self._restock_watch()
        watch['restock'] = Restock({'in_stock': True, 'price': 50.0, 'last_price': 100.0})
        self.assertTrue(watch_is_deal(watch))


if __name__ == '__main__':
    unittest.main()
