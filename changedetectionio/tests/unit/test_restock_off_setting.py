#!/usr/bin/env python3
"""
Regression for #4476: "Re-stock detection" setting not respected.

dgtlmoon clarified (discussion #4067) that the real trigger was a page with no embedded
price/availability data at all (a bot-block page) - the check is right to fail there in every
mode, restock detection off or not, since there's genuinely nothing to compare on future checks.
The actual bug is the wording: with 'in_stock_processing' == 'off' the user has said they don't
care about stock, so the failure here is about price extraction, not "restock"/stock data - the
error message must say so instead of talking about stock information.

Run from the tests/ directory:
    python -m unittest unit/test_restock_off_setting.py
"""
import shutil
import tempfile
import time
import unittest

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.processors.exceptions import ProcessorException
from changedetectionio.processors.restock_diff.processor import perform_site_check
from changedetectionio.content_fetchers.base import Fetcher

# No structured price, no availability, nothing a scraper would call "interesting" either.
NOTHING_EXTRACTABLE_HTML = """<html><body>
<p>Please verify you are not a robot.</p>
</body></html>"""


class TestRestockOffSetting(unittest.TestCase):
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

    def test_off_with_nothing_extractable_still_raises_with_price_specific_message(self):
        """'off' + a page with nothing extractable at all must still raise (there's nothing to
        track on future checks either), but the message must talk about price, not restock/stock
        data, since the user turned stock checking off."""
        uuid = self.store.add_watch(url='https://example.com/product', extras={'processor': 'restock_diff'})
        watch = self.store.data['watching'][uuid]

        proc = perform_site_check(self.store, uuid)
        proc.update_extra_watch_config(
            'restock_diff.json',
            {'restock_diff': {'in_stock_processing': 'off', 'follow_price_changes': True}},
            merge=False,
        )

        proc.fetcher = Fetcher()
        proc.fetcher.content = NOTHING_EXTRACTABLE_HTML
        proc.fetcher.headers = {}
        proc.fetcher.status_code = 200
        proc.fetcher.instock_data = None
        proc.fetcher.backend_name = None
        proc.fetcher.screenshot = None
        proc.fetcher.xpath_data = None

        with self.assertRaises(ProcessorException) as ctx:
            proc.run_changedetection(watch)

        self.assertIn('price', ctx.exception.message.lower())
        self.assertNotIn('stock', ctx.exception.message.lower())


if __name__ == '__main__':
    unittest.main()
