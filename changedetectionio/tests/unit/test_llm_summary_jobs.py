#!/usr/bin/env python3

"""The AI-summary job registry must never pay for the same summary twice.

The /llm-summary route is now start-then-wait: a POST kicks off generation on this pool, and the
browser finds out it finished either from the llm_summary_ready Socket.IO event or by polling the
route. That turns duplicate-suppression into a correctness requirement rather than a nicety - a
caller that decides "nothing is running" starts a *second* LLM call and bills the operator twice
for one summary. Two tabs on the same watch hit the same path.

What this asserts, in the order it matters:
  - concurrent submits for one key produce exactly one run
  - the pending flag is visible from the moment submit() returns (no gap for a poll to fall into)
  - the flag clears only after the job function has returned, i.e. after it has written its result
  - failures are held for exactly one reader instead of dying with the thread
  - a different key is never suppressed
  - the "job settled" announcement fires after the result is readable, and cannot break the job
  - a running job reports when it started, so the routes can hand the browser a real deadline

run from dir above changedetectionio/ dir
python3 -m unittest changedetectionio.tests.unit.test_llm_summary_jobs
"""

import threading
import unittest

from changedetectionio.llm.summary_jobs import SummaryJobFailed, SummaryJobRegistry


class TestSummaryJobRegistry(unittest.TestCase):

    def setUp(self):
        self.reg = SummaryJobRegistry(max_workers=4)

    def _wait_until_idle(self, key, timeout=5, reg=None):
        reg = reg or self.reg
        done = threading.Event()

        def _poll():
            if not reg.is_pending(key):
                done.set()
        for _ in range(int(timeout * 100)):
            _poll()
            if done.is_set():
                return True
            threading.Event().wait(0.01)
        return not reg.is_pending(key)

    def test_duplicate_submit_runs_once(self):
        """The whole point: N callers, one LLM call."""
        runs = []
        release = threading.Event()
        entered = threading.Event()

        def job():
            runs.append(1)
            entered.set()
            release.wait(5)

        accepted = [self.reg.submit('k', job) for _ in range(5)]

        self.assertTrue(entered.wait(5), "job never started")
        self.assertEqual(accepted, [True, False, False, False, False],
                         "only the first submit should start work")
        release.set()
        self.assertTrue(self._wait_until_idle('k'))
        self.assertEqual(len(runs), 1, f"job ran {len(runs)} times, expected exactly 1")

    def test_pending_is_visible_immediately_after_submit(self):
        """A poll arriving between submit() and the worker starting must still see 'pending'.

        If it saw 'idle' it would start a duplicate generation.
        """
        release = threading.Event()
        self.reg.submit('k', lambda: release.wait(5))
        self.assertTrue(self.reg.is_pending('k'))
        release.set()
        self.assertTrue(self._wait_until_idle('k'))
        self.assertFalse(self.reg.is_pending('k'))

    def test_pending_clears_only_after_job_body_completes(self):
        """Ordering guard: the result is written inside the job, so the flag must outlive it."""
        wrote = []
        gate = threading.Event()

        def job():
            gate.wait(5)
            wrote.append('saved')      # stands in for save_llm_diff_summary()

        self.reg.submit('k', job)
        self.assertTrue(self.reg.is_pending('k'))
        self.assertEqual(wrote, [], "job body should not have finished yet")
        gate.set()
        self.assertTrue(self._wait_until_idle('k'))
        self.assertEqual(wrote, ['saved'],
                         "pending cleared before the job wrote its result - a poll could now "
                         "see neither a cached summary nor a running job and re-bill the LLM")

    def test_run_started_at_is_stamped_only_while_the_job_actually_runs(self):
        """The deadline the browser counts down to is anchored to this.

        A job queued behind another generation has not started burning its LLM timeout yet, so it
        must report None (the route then measures from now and the deadline keeps sliding) rather
        than a start time that would expire while it is still waiting for a worker.
        """
        reg = SummaryJobRegistry(max_workers=1)
        release = threading.Event()
        running = threading.Event()

        def first():
            running.set()
            release.wait(5)

        reg.submit('busy', first)
        reg.submit('queued', lambda: None)
        self.assertTrue(running.wait(5), "first job never started")

        self.assertIsNotNone(reg.run_started_at('busy'), "a running job must report its start")
        self.assertIsNone(reg.run_started_at('queued'),
                          "a job still waiting for a worker has not started its timeout")

        release.set()
        self.assertTrue(self._wait_until_idle('busy', reg=reg))
        self.assertIsNone(reg.run_started_at('busy'),
                          "a finished job must not keep reporting a start time")

    def test_handled_failure_is_delivered_once_with_its_status(self):
        def job():
            raise SummaryJobFailed('Input too large', http_status=400)

        self.reg.submit('k', job)
        self.assertTrue(self._wait_until_idle('k'))

        self.assertEqual(self.reg.take_error('k'), (400, 'Input too large'))
        self.assertIsNone(self.reg.take_error('k'), "an error must not be delivered twice")

    def test_unexpected_exception_becomes_a_500(self):
        def job():
            raise RuntimeError('provider exploded')

        self.reg.submit('k', job)
        self.assertTrue(self._wait_until_idle('k'))

        status, message = self.reg.take_error('k')
        self.assertEqual(status, 500)
        self.assertIn('provider exploded', message)

    def test_failure_does_not_leave_the_key_pending(self):
        """Otherwise the watch is permanently un-summarisable until restart."""
        self.reg.submit('k', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        self.assertTrue(self._wait_until_idle('k'))
        self.assertFalse(self.reg.is_pending('k'))

    def test_a_new_submit_clears_a_stale_error(self):
        self.reg.submit('k', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        self.assertTrue(self._wait_until_idle('k'))

        self.reg.submit('k', lambda: None)
        self.assertTrue(self._wait_until_idle('k'))
        self.assertIsNone(self.reg.take_error('k'),
                          "a retry that succeeded must not report the previous failure")

    def test_distinct_keys_are_independent(self):
        runs = []
        release = threading.Event()

        def job(name):
            runs.append(name)
            release.wait(5)

        self.assertTrue(self.reg.submit('watch-a', lambda: job('a')))
        self.assertTrue(self.reg.submit('watch-b', lambda: job('b')),
                        "a different version pair / prompt must not be suppressed")
        release.set()
        self.assertTrue(self._wait_until_idle('watch-a'))
        self.assertTrue(self._wait_until_idle('watch-b'))
        self.assertEqual(sorted(runs), ['a', 'b'])

    def test_on_settled_fires_after_the_result_is_readable(self):
        """The Socket.IO announcement must not arrive before the result it announces.

        The browser answers this event with a single fetch (it does not poll in realtime mode), so
        if the event were sent while the key still looked pending, that one fetch would come back
        'pending' and the client would wait for an event that had already been sent.
        """
        observed = {}

        def job():
            pass

        def on_settled(key):
            observed['pending_at_announce'] = self.reg.is_pending(key)
            observed['key'] = key

        self.reg.submit('k', job, on_settled=on_settled)
        self.assertTrue(self._wait_until_idle('k'))
        for _ in range(500):
            if 'key' in observed:
                break
            threading.Event().wait(0.01)

        self.assertEqual(observed.get('key'), 'k')
        self.assertFalse(observed.get('pending_at_announce'),
                         "announced while the job still looked pending")

    def test_on_settled_fires_on_failure_too(self):
        """Otherwise a failed generation would only surface via the slow watchdog re-check."""
        seen = []

        def job():
            raise SummaryJobFailed('nope', http_status=400)

        self.reg.submit('k', job, on_settled=lambda key: seen.append(key))
        self.assertTrue(self._wait_until_idle('k'))
        for _ in range(500):
            if seen:
                break
            threading.Event().wait(0.01)

        self.assertEqual(seen, ['k'])
        self.assertEqual(self.reg.take_error('k'), (400, 'nope'),
                         "the error must be readable by the time the client is told to look")

    def test_a_broken_on_settled_does_not_break_the_job(self):
        self.reg.submit('k', lambda: None, on_settled=lambda key: 1 / 0)
        self.assertTrue(self._wait_until_idle('k'))
        self.assertFalse(self.reg.is_pending('k'))
        self.assertIsNone(self.reg.take_error('k'),
                          "a failed announcement must not be reported as a generation failure")

    def test_no_threads_are_started_at_construction(self):
        """Pool is lazy - import/construct must not spawn threads that outlive gc.freeze()."""
        reg = SummaryJobRegistry()
        self.assertIsNone(reg._pool)
        reg.submit('k', lambda: None)
        self.assertIsNotNone(reg._pool)


if __name__ == '__main__':
    unittest.main()
