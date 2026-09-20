#!/usr/bin/env python3
"""
The /llm-summary route is start-then-wait, not a blocking request.

Generating a summary is an LLM round-trip, so the route no longer holds a request thread for it:
POST starts the work on a small pool and answers 202, and a read-only GET picks the result up out
of the watch's summary cache - driven either by the llm_summary_ready event (realtime) or by
polling (no realtime). These tests pin the properties that make that safe:

  - POST answers immediately instead of waiting for the LLM
  - a second click (or a poll) never starts a duplicate generation - that would bill twice
  - the GET is genuinely read-only, so it is safe to leave it as a GET
  - completion announces itself, since a realtime client makes exactly one request per event

plus the CSRF protection on the POST, which is the reason starting generation is not a GET in the
first place: a bare <img src="/diff/<uuid>/llm-summary"> on any page would otherwise spend the
operator's tokens and mark the watch as viewed.
"""

import threading
import time

from unittest.mock import MagicMock, patch

from flask import url_for

from changedetectionio.tests.util import delete_all_watches, fetch_llm_summary


def _configure_llm(client):
    ds = client.application.config.get('DATASTORE')
    existing = ds.data['settings']['application'].get('llm') or {}
    existing.update({'model': 'gpt-4o-mini', 'api_key': 'sk-test'})
    ds.data['settings']['application']['llm'] = existing


def _watch_with_history(client, from_ts, to_ts):
    ds = client.application.config.get('DATASTORE')
    test_url = url_for('test_endpoint', content_type='text/html', content='v1', _external=True)
    uuid = ds.add_watch(url=test_url)
    watch = ds.data['watching'][uuid]
    watch.save_history_blob('old content\n', from_ts, 'snap-old')
    watch.save_history_blob('new content\n', to_ts, 'snap-new')
    return uuid, watch


def _llm_response(text='Content changed from old to new.'):
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = text
    mock_response.usage = MagicMock(total_tokens=50, prompt_tokens=40, completion_tokens=10)
    return mock_response


def test_post_returns_pending_then_poll_returns_summary(
        client, live_server, measure_memory_usage, datastore_path):
    """The POST must not block on the LLM: it answers 202, the summary arrives via the poll."""
    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5000000000', '5000000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5000000000', to_version='5000000001')

    released = threading.Event()

    def slow_completion(*args, **kwargs):
        released.wait(10)
        return _llm_response()

    with patch('litellm.completion', side_effect=slow_completion):
        start = client.post(url)
        assert start.status_code == 202, "POST should hand off to the background pool"
        assert start.get_json()['status'] == 'pending'
        assert start.get_json()['summary'] is None

        # Still generating — the poll reports pending without starting anything of its own
        pending = client.get(url)
        assert pending.status_code == 202
        assert pending.get_json()['status'] == 'pending'

        released.set()

        deadline = time.time() + 15
        while time.time() < deadline:
            res = client.get(url)
            if res.status_code != 202:
                break
            time.sleep(0.05)

    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'done'
    assert data['summary'] == 'Content changed from old to new.'

    delete_all_watches(client)


def test_repeated_clicks_generate_one_summary(
        client, live_server, measure_memory_usage, datastore_path):
    """Two tabs / an impatient double-click must not pay for the same summary twice."""
    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5100000000', '5100000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5100000000', to_version='5100000001')

    calls = {'n': 0}
    released = threading.Event()
    entered = threading.Event()

    def slow_completion(*args, **kwargs):
        calls['n'] += 1
        entered.set()
        released.wait(10)
        return _llm_response()

    try:
        with patch('litellm.completion', side_effect=slow_completion):
            first = client.post(url)
            assert first.status_code == 202
            assert entered.wait(10), "background job never reached the LLM call"

            # Extra clicks while the first generation is still running
            for _ in range(3):
                again = client.post(url)
                assert again.status_code == 202
                assert again.get_json()['status'] == 'pending'

            released.set()

            deadline = time.time() + 15
            while time.time() < deadline:
                res = client.get(url)
                if res.status_code != 202:
                    break
                time.sleep(0.05)
    finally:
        released.set()

    assert res.status_code == 200
    assert res.get_json()['summary'] == 'Content changed from old to new.'
    assert calls['n'] == 1, f"LLM was called {calls['n']} times for one summary"

    # And once cached, a further click is answered straight from disk — still no new call
    with patch('litellm.completion', side_effect=slow_completion):
        cached = client.post(url)
    assert cached.status_code == 200
    assert cached.get_json()['cached'] is True
    assert calls['n'] == 1

    delete_all_watches(client)


def test_poll_alone_never_starts_generation(
        client, live_server, measure_memory_usage, datastore_path):
    """The GET is read-only — that is what makes it safe to leave CSRF-exempt.

    With nothing cached and no job running it reports 'idle' so the client re-POSTs, rather than
    quietly spending tokens on a request that carried no CSRF token.
    """
    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5200000000', '5200000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5200000000', to_version='5200000001')

    calls = {'n': 0}

    def counted(*args, **kwargs):
        calls['n'] += 1
        return _llm_response()

    with patch('litellm.completion', side_effect=counted):
        for _ in range(3):
            res = client.get(url)
            assert res.status_code == 200
            assert res.get_json()['status'] == 'idle'
            assert res.get_json()['summary'] is None

    assert calls['n'] == 0, "a GET poll must never trigger an LLM call"
    assert watch['last_viewed'] == 0, "a GET poll must not mark the watch as viewed either"

    delete_all_watches(client)


def test_starting_generation_requires_a_csrf_token(
        client, live_server, measure_memory_usage, datastore_path):
    """Starting a generation spends tokens, so it must be CSRF-protected.

    conftest disables CSRF for the test client, so switch it back on for this one check to prove
    the route is actually covered by CSRFProtect (i.e. it was not exempted the way the JSON API is
    via `csrf.exempt`).
    """
    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5300000000', '5300000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5300000000', to_version='5300000001')

    calls = {'n': 0}

    def counted(*args, **kwargs):
        calls['n'] += 1
        return _llm_response()

    app = client.application
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        with patch('litellm.completion', side_effect=counted):
            res = client.post(url)          # no token supplied
            assert res.status_code in (400, 403), \
                f"POST without a CSRF token was accepted ({res.status_code})"

            # The read-only poll is unaffected
            poll = client.get(url)
            assert poll.status_code == 200
            assert poll.get_json()['status'] == 'idle'
    finally:
        app.config['WTF_CSRF_ENABLED'] = False

    assert calls['n'] == 0, "a request rejected for CSRF must not have reached the LLM"

    delete_all_watches(client)


def test_a_job_finishing_mid_request_is_not_reported_as_idle(
        client, live_server, measure_memory_usage, datastore_path):
    """Regression: the poll must re-read the cache before it declares nothing is running.

    A job writes the summary and *then* clears its pending flag, so a request that reads the cache
    (miss), then checks the flag a moment later (clear), would announce 'idle' for a summary that
    is already on disk - and send the client back to POST, which is the request that spends money.
    Simulated by making the first cache read miss and the second one hit.
    """
    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5600000000', '5600000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5600000000', to_version='5600000001')

    with patch.object(type(watch), 'get_llm_diff_summary',
                      side_effect=['', 'Summary that landed mid-request.']):
        res = client.get(url)

    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'done', f"poll reported {data['status']!r} for a cached summary"
    assert data['summary'] == 'Summary that landed mid-request.'

    delete_all_watches(client)


def test_completion_emits_llm_summary_ready_signal(
        client, live_server, measure_memory_usage, datastore_path):
    """Realtime clients do not poll, so the signal the socket server re-broadcasts must fire.

    Asserted at the blinker signal rather than through a Socket.IO client: that is the seam the
    socket server subscribes to, and it stays a no-op when realtime is disabled.
    """
    from blinker import signal

    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5500000000', '5500000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5500000000', to_version='5500000001')

    received = []
    fired = threading.Event()

    def listener(sender, **kwargs):
        received.append(kwargs)
        fired.set()

    sig = signal('llm_summary_ready')
    sig.connect(listener, weak=False)
    try:
        with patch('litellm.completion', return_value=_llm_response()):
            assert client.post(url).status_code == 202
            assert fired.wait(15), "job finished without announcing llm_summary_ready"
    finally:
        sig.disconnect(listener)

    assert received[0]['watch_uuid'] == uuid
    assert received[0]['from_version'] == '5500000000'
    assert received[0]['to_version'] == '5500000001'

    # The announcement means "go look" - the summary must already be readable by then, because a
    # realtime client makes exactly one request in response to it.
    res = client.get(url)
    assert res.status_code == 200
    assert res.get_json()['summary'] == 'Content changed from old to new.'

    delete_all_watches(client)


def test_generation_failure_reaches_the_poller_once(
        client, live_server, measure_memory_usage, datastore_path):
    """A failure in the background thread must surface, not leave a permanent spinner."""
    import litellm as _real_litellm

    _configure_llm(client)
    uuid, watch = _watch_with_history(client, '5400000000', '5400000001')
    url = url_for('ui.ui_diff.diff_llm_summary', uuid=uuid,
                  from_version='5400000000', to_version='5400000001')

    exc = _real_litellm.AuthenticationError(
        'litellm.AuthenticationError: Invalid API key.',
        llm_provider='openai', model='gpt-4o-mini',
    )

    with patch('litellm.completion', side_effect=exc):
        res = fetch_llm_summary(client, url)

    assert res.status_code == 500
    data = res.get_json()
    assert data['summary'] is None
    assert data['error']
    assert data['status'] == 'error'

    # Delivered once: the next poll is back to 'idle' rather than repeating a stale failure
    followup = client.get(url)
    assert followup.status_code == 200
    assert followup.get_json()['status'] == 'idle'

    delete_all_watches(client)
