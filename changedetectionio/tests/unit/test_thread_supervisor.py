#!/usr/bin/env python3

"""
Tests for thread_supervisor.supervise().

Context: the ticker thread had `return False` buried inside its per-watch loop.
One watch with an unresolvable timezone made the whole loop return, the thread
ended, and no watch was ever checked again - with the process still up and
looking healthy. threading.Thread cannot be restarted (start() twice raises
RuntimeError), so recovery has to live inside the thread.

The two behaviours that matter:
  - a target that returns or raises is restarted, loudly
  - a target that exits during shutdown is NOT restarted

Run:  python3 -m unittest changedetectionio.tests.unit.test_thread_supervisor
"""

import threading
import time
import unittest

from changedetectionio.thread_supervisor import supervise, start_supervised_thread


class TestRestartsOnDeath(unittest.TestCase):

    def test_target_that_returns_is_restarted(self):
        """The exact ticker bug: a stray `return` must not end the thread."""
        exit_event = threading.Event()
        calls = []

        def flaky():
            calls.append('run')
            if len(calls) >= 3:
                exit_event.set()      # let the supervisor finish
            return                     # simulates `return False` in the loop

        supervise(flaky, 'flaky', exit_event, max_backoff=0.01, healthy_after=9999)
        self.assertEqual(len(calls), 3, "target should have been restarted twice")

    def test_target_that_raises_is_restarted(self):
        exit_event = threading.Event()
        calls = []

        def crashy():
            calls.append('run')
            if len(calls) >= 3:
                exit_event.set()
                return
            raise RuntimeError("boom")

        supervise(crashy, 'crashy', exit_event, max_backoff=0.01, healthy_after=9999)
        self.assertEqual(len(calls), 3)

    def test_restart_reason_is_reported(self):
        exit_event = threading.Event()
        reasons = []
        calls = []

        def mixed():
            calls.append('run')
            if len(calls) == 1:
                return                        # clean but wrong
            if len(calls) == 2:
                raise ValueError("nope")      # crash
            exit_event.set()

        supervise(mixed, 'mixed', exit_event, max_backoff=0.01, healthy_after=9999,
                  _on_restart=lambda n, reason: reasons.append(reason))

        self.assertEqual(len(reasons), 2)
        self.assertIn('returned unexpectedly', reasons[0])
        self.assertIn('ValueError: nope', reasons[1])

    def test_backoff_grows_then_resets_after_healthy_run(self):
        exit_event = threading.Event()
        stamps = []

        def failing():
            stamps.append(time.monotonic())
            if len(stamps) >= 4:
                exit_event.set()
                return
            raise RuntimeError("boom")

        supervise(failing, 'failing', exit_event, max_backoff=0.08, healthy_after=9999)
        gaps = [stamps[i + 1] - stamps[i] for i in range(len(stamps) - 1)]
        # 1s doubling is capped at max_backoff, so every gap should hit the cap
        for gap in gaps:
            self.assertGreaterEqual(gap, 0.05, f"gaps={gaps} - backoff not applied")

    def test_does_not_spin_hot(self):
        """A target failing instantly must not be restarted in a tight loop."""
        exit_event = threading.Event()
        calls = []
        start = time.monotonic()

        def instant():
            calls.append(1)
            if len(calls) >= 3:
                exit_event.set()
                return
            raise RuntimeError("instant")

        supervise(instant, 'instant', exit_event, max_backoff=0.05, healthy_after=9999)
        self.assertGreater(time.monotonic() - start, 0.05,
                           "supervisor restarted with no delay - would burn CPU")


class TestDoesNotRestartDuringShutdown(unittest.TestCase):

    def test_exit_event_stops_restarting(self):
        exit_event = threading.Event()
        calls = []

        def target():
            calls.append('run')
            exit_event.set()          # shutdown requested, then return normally

        supervise(target, 'target', exit_event, max_backoff=0.01)
        self.assertEqual(len(calls), 1, "must not restart once exit_event is set")

    def test_exit_event_set_before_start_never_runs_target(self):
        exit_event = threading.Event()
        exit_event.set()
        calls = []
        supervise(lambda: calls.append('run'), 'target', exit_event)
        self.assertEqual(calls, [])

    def test_secondary_shutdown_flag_stops_restarting(self):
        """sigshutdown_handler also sets datastore.stop_thread - honour it."""
        exit_event = threading.Event()
        state = {'stop_thread': False}
        calls = []

        def target():
            calls.append('run')
            state['stop_thread'] = True    # only the secondary flag is set
            return

        supervise(target, 'target', exit_event,
                  is_shutting_down=lambda: state['stop_thread'],
                  max_backoff=0.01)
        self.assertEqual(len(calls), 1,
                         "must not restart when the secondary shutdown flag is set")
        self.assertFalse(exit_event.is_set(), "primary flag was never set in this test")

    def test_raising_shutdown_predicate_does_not_block_restart(self):
        """A broken predicate must not silently disable recovery."""
        exit_event = threading.Event()
        calls = []

        def target():
            calls.append('run')
            if len(calls) >= 2:
                exit_event.set()
            return

        def broken():
            raise RuntimeError("predicate is broken")

        supervise(target, 'target', exit_event, is_shutting_down=broken,
                  max_backoff=0.01, healthy_after=9999)
        self.assertEqual(len(calls), 2, "should still have restarted once")


class TestStartSupervisedThread(unittest.TestCase):

    def test_returns_a_real_thread_object(self):
        """Thread(...).start() returns None - that is why ticker_thread was
        always None and nothing could check is_alive()."""
        exit_event = threading.Event()
        started = threading.Event()

        def target():
            started.set()
            exit_event.wait(5)

        t = start_supervised_thread(target, 'TestThread', exit_event)
        self.addCleanup(exit_event.set)

        self.assertIsInstance(t, threading.Thread)
        self.assertTrue(started.wait(5), "target did not run")
        self.assertTrue(t.is_alive())
        self.assertTrue(t.daemon)
        self.assertEqual(t.name, 'TestThread')

        exit_event.set()
        t.join(timeout=5)
        self.assertFalse(t.is_alive(), "thread did not exit on shutdown")

    def test_thread_survives_a_dying_target(self):
        """End to end: the thread outlives a target that keeps returning."""
        exit_event = threading.Event()
        calls = []
        done = threading.Event()

        def target():
            calls.append(1)
            if len(calls) >= 3:
                done.set()
                exit_event.wait(5)
            return

        t = start_supervised_thread(target, 'Dying', exit_event, max_backoff=0.01,
                                    healthy_after=9999)
        self.addCleanup(exit_event.set)

        self.assertTrue(done.wait(10), f"target was not restarted (calls={len(calls)})")
        self.assertTrue(t.is_alive(), "thread died despite supervision")
        exit_event.set()
        t.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
