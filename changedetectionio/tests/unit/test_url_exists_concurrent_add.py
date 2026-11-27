#!/usr/bin/env python3
"""
url_exists() must not fail while another thread adds a watch.

An API import of 20 or more URLs adds its watches in a background thread. A second
import with dedupe=true calls url_exists() for each URL, which walks the watch list.
If the background thread adds a watch during that walk, Python raises
"RuntimeError: dictionary changed size during iteration" and the import returns 500.

The test makes that interleaving happen every time, with no timing involved: the watch
list is swapped for one whose walk starts a real add_watch() on another thread at its
first step, and pauses until that thread either inserts its watch (no lock: the walk then
fails) or is blocked on the datastore lock (lock held: the walk finishes first).

Run from the tests/ directory:
    python -m unittest unit/test_url_exists_concurrent_add.py
"""

import shutil
import tempfile
import threading
import time
import unittest

from changedetectionio.store import ChangeDetectionStore


class LockThatReportsContention:
    """The datastore lock, plus an event set when a thread has to wait for it."""

    def __init__(self, lock, contended):
        self.lock = lock
        self.contended = contended

    def __enter__(self):
        if not self.lock.acquire(blocking=False):
            self.contended.set()
            self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


class WatchesThatGrowWhileWalked(dict):
    """A watch dict whose values() walk lets another thread add a watch mid-walk."""

    def __init__(self, *args, on_first_step=None, inserted=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_first_step = on_first_step
        self.inserted = inserted

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.inserted.set()

    def values(self):
        first = True
        for value in super().values():
            if first and self.on_first_step:
                first = False
                hook, self.on_first_step = self.on_first_step, None
                hook()
            yield value


class TestUrlExistsWhileAdding(unittest.TestCase):
    def setUp(self):
        self.test_datastore_path = tempfile.mkdtemp()
        self.store = ChangeDetectionStore(
            datastore_path=self.test_datastore_path,
            include_default_watches=False,
        )
        for n in range(3):
            self.store.add_watch(url=f"https://existing-{n}.example.com")

    def tearDown(self):
        self.store.stop_thread = True
        time.sleep(0.5)
        shutil.rmtree(self.test_datastore_path, ignore_errors=True)

    def test_url_exists_survives_a_concurrent_add_watch(self):
        # Set when the other thread has inserted its watch, or is waiting on the lock.
        settled = threading.Event()
        self.store.lock = LockThatReportsContention(self.store.lock, settled)

        adder = threading.Thread(
            target=self.store.add_watch, kwargs={"url": "https://added-meanwhile.example.com"}
        )
        self.addCleanup(adder.join, 10)

        def add_from_another_thread():
            adder.start()
            self.assertTrue(settled.wait(timeout=10), "add_watch() neither inserted nor waited")

        # store.data is the datastore's own dict (not a copy), so this swaps the live list.
        self.store.data['watching'] = WatchesThatGrowWhileWalked(
            self.store.data['watching'], on_first_step=add_from_another_thread, inserted=settled
        )

        self.assertFalse(self.store.url_exists("https://not-watched.example.com"))
        adder.join(timeout=10)
        self.assertFalse(adder.is_alive())
        self.assertTrue(self.store.url_exists("https://added-meanwhile.example.com"))

    def test_url_exists_still_matches_case_insensitively(self):
        self.assertTrue(self.store.url_exists("HTTPS://EXISTING-1.example.com"))
        self.assertFalse(self.store.url_exists("https://existing-9.example.com"))


if __name__ == '__main__':
    unittest.main()
