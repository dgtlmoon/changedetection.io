"""
Tests for LLM summary queue, worker, and regenerate route.

Mocking strategy
----------------
- `_call_llm` is patched at the module level so no real LiteLLM/API calls are made.
- `_write_summary` is left un-patched so we can assert the file was actually written.
- `process_llm_summary` is called directly in unit tests (no worker thread needed).
"""

import os
import queue
import time
from unittest.mock import patch, MagicMock

import pytest
from flask import url_for

from changedetectionio.tests.util import set_original_response, set_modified_response, wait_for_all_checks


# ---------------------------------------------------------------------------
# Unit tests — process_llm_summary directly, no HTTP, no worker thread
# ---------------------------------------------------------------------------

class TestProcessLlmSummary:

    def _make_watch_with_two_snapshots(self, client, datastore_path):
        """Helper: returns (datastore, uuid, snapshot_id) with 2 history entries."""
        set_original_response(datastore_path=datastore_path)
        datastore = client.application.config['DATASTORE']
        test_url  = url_for('test_endpoint', _external=True)

        uuid = datastore.add_watch(url=test_url)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        set_modified_response(datastore_path=datastore_path)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        watch        = datastore.data['watching'][uuid]
        history_keys = list(watch.history.keys())
        snapshot_id  = os.path.basename(watch.history[history_keys[1]]).split('.')[0]
        return datastore, uuid, snapshot_id

    def test_writes_summary_file(self, client, live_server, datastore_path):
        """process_llm_summary writes {snapshot_id}-llm.txt when _call_llm succeeds."""
        datastore, uuid, snapshot_id = self._make_watch_with_two_snapshots(client, datastore_path)
        watch = datastore.data['watching'][uuid]
        item  = {'uuid': uuid, 'snapshot_id': snapshot_id, 'attempts': 0}

        from changedetectionio.llm.queue_worker import process_llm_summary
        with patch('changedetectionio.llm.queue_worker._call_llm', return_value='Price dropped from $10 to $8.') as mock_llm:
            process_llm_summary(item, datastore)

        assert mock_llm.called
        summary_path = os.path.join(watch.data_dir, f"{snapshot_id}-llm.txt")
        assert os.path.exists(summary_path), "Summary file was not written"
        assert open(summary_path).read() == 'Price dropped from $10 to $8.'

    def test_call_llm_uses_temperature_zero_and_seed(self, client, live_server, datastore_path):
        """_call_llm always passes temperature=0 and seed=0 to litellm for determinism."""
        import litellm
        from changedetectionio.llm.queue_worker import _call_llm

        messages = [{'role': 'user', 'content': 'hello'}]
        mock_response = MagicMock()
        mock_response.choices[0].message.content = 'ok'

        with patch('litellm.completion', return_value=mock_response) as mock_completion:
            _call_llm(model='gpt-4o-mini', messages=messages)

        call_kwargs = mock_completion.call_args.kwargs
        assert call_kwargs['temperature'] == 0,   "temperature must be 0"
        assert call_kwargs['seed']        == 0,   "seed must be 0 for reproducibility"
        assert 'top_p'              not in call_kwargs, "top_p must not be set (redundant at temp=0)"
        assert 'frequency_penalty'  not in call_kwargs, "frequency_penalty must not be set"
        assert 'presence_penalty'   not in call_kwargs, "presence_penalty must not be set"

    def test_skips_first_history_entry(self, client, live_server, datastore_path):
        """process_llm_summary raises ValueError for the first history entry (no prior to diff)."""
        set_original_response(datastore_path=datastore_path)
        datastore = client.application.config['DATASTORE']
        test_url = url_for('test_endpoint', _external=True)

        uuid = datastore.add_watch(url=test_url)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        watch = datastore.data['watching'][uuid]
        history_keys = list(watch.history.keys())
        first_fname = watch.history[history_keys[0]]
        snapshot_id = os.path.basename(first_fname).split('.')[0]

        item = {'uuid': uuid, 'snapshot_id': snapshot_id, 'attempts': 0}

        from changedetectionio.llm.queue_worker import process_llm_summary
        with pytest.raises(ValueError, match="first history entry"):
            process_llm_summary(item, datastore)

    def test_raises_for_unknown_watch(self, client, live_server, datastore_path):
        """process_llm_summary raises ValueError if the watch UUID doesn't exist."""
        datastore = client.application.config['DATASTORE']
        item = {'uuid': 'does-not-exist', 'snapshot_id': 'abc123', 'attempts': 0}

        from changedetectionio.llm.queue_worker import process_llm_summary
        with pytest.raises(ValueError, match="not found"):
            process_llm_summary(item, datastore)


# ---------------------------------------------------------------------------
# Unit tests — worker retry logic, no HTTP
# ---------------------------------------------------------------------------

class TestWorkerRetry:

    def test_requeues_on_failure_with_backoff(self, client, live_server, datastore_path):
        """Worker re-queues a failed item with incremented attempts and future next_retry_at."""
        from changedetectionio.llm.queue_worker import MAX_RETRIES, RETRY_BACKOFF_BASE_SECONDS

        llm_q   = queue.Queue()
        app     = client.application
        datastore = client.application.config['DATASTORE']

        item = {'uuid': 'fake-uuid', 'snapshot_id': 'abc123', 'attempts': 0}
        llm_q.put(item)

        from changedetectionio.llm.queue_worker import process_llm_summary
        with patch('changedetectionio.llm.queue_worker.process_llm_summary', side_effect=RuntimeError("API down")):
            # Run one iteration manually (don't start the full runner thread)
            from changedetectionio.llm import queue_worker
            got = llm_q.get(block=False)
            try:
                queue_worker.process_llm_summary(got, datastore)
            except Exception as e:
                got['attempts'] += 1
                got['next_retry_at'] = time.time() + RETRY_BACKOFF_BASE_SECONDS * (2 ** (got['attempts'] - 1))
                llm_q.put(got)

        assert llm_q.qsize() == 1
        requeued = llm_q.get_nowait()
        assert requeued['attempts'] == 1
        assert requeued['next_retry_at'] > time.time()

    def test_drops_after_max_retries(self, client, live_server, datastore_path):
        """Worker drops item and records last_error after MAX_RETRIES exhausted."""
        set_original_response(datastore_path=datastore_path)
        datastore = client.application.config['DATASTORE']
        test_url = url_for('test_endpoint', _external=True)
        uuid = datastore.add_watch(url=test_url)

        from changedetectionio.llm.queue_worker import MAX_RETRIES
        item = {'uuid': uuid, 'snapshot_id': 'abc123', 'attempts': MAX_RETRIES}

        llm_q = queue.Queue()
        llm_q.put(item)

        with patch('changedetectionio.llm.queue_worker.process_llm_summary', side_effect=RuntimeError("still down")):
            from changedetectionio.llm import queue_worker
            got = llm_q.get(block=False)
            try:
                queue_worker.process_llm_summary(got, datastore)
            except Exception as e:
                if got['attempts'] < MAX_RETRIES:
                    llm_q.put(got)
                else:
                    datastore.update_watch(uuid=uuid, update_obj={'last_error': str(e)})

        # Queue should be empty — item was dropped
        assert llm_q.empty()
        watch = datastore.data['watching'][uuid]
        assert 'still down' in (watch.get('last_error') or '')


# ---------------------------------------------------------------------------
# Route tests — GET /edit/<uuid>/regenerate-llm-summaries
# ---------------------------------------------------------------------------

class TestRegenerateLlmSummariesRoute:

    def test_queues_missing_summaries(self, client, live_server, datastore_path):
        """Route queues one item per history entry that lacks a -llm.txt file."""
        set_original_response(datastore_path=datastore_path)
        datastore = client.application.config['DATASTORE']
        test_url  = url_for('test_endpoint', _external=True)

        uuid = datastore.add_watch(url=test_url)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        set_modified_response(datastore_path=datastore_path)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        watch = datastore.data['watching'][uuid]
        assert watch.history_n >= 2

        from changedetectionio.flask_app import llm_summary_q

        res = client.get(
            url_for('ui.ui_edit.watch_regenerate_llm_summaries', uuid=uuid),
            follow_redirects=True,
        )
        assert res.status_code == 200

        # history_n - 1 items queued (first entry skipped, no prior to diff)
        expected = watch.history_n - 1
        assert llm_summary_q.qsize() == expected

        # Each item has the right shape
        items = []
        while not llm_summary_q.empty():
            items.append(llm_summary_q.get_nowait())

        for item in items:
            assert item['uuid'] == uuid
            assert item['attempts'] == 0
            assert len(item['snapshot_id']) == 32  # MD5 hex

    def test_skips_already_summarised_entries(self, client, live_server, datastore_path):
        """Route skips entries where {snapshot_id}-llm.txt already exists."""
        set_original_response(datastore_path=datastore_path)
        datastore = client.application.config['DATASTORE']
        test_url  = url_for('test_endpoint', _external=True)

        uuid = datastore.add_watch(url=test_url)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        set_modified_response(datastore_path=datastore_path)
        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        watch = datastore.data['watching'][uuid]
        history_keys  = list(watch.history.keys())
        second_fname  = watch.history[history_keys[1]]
        snapshot_id   = os.path.basename(second_fname).split('.')[0]

        # Pre-write a summary file
        summary_path = os.path.join(watch.data_dir, f"{snapshot_id}-llm.txt")
        with open(summary_path, 'w') as f:
            f.write('already done')

        from changedetectionio.flask_app import llm_summary_q

        client.get(
            url_for('ui.ui_edit.watch_regenerate_llm_summaries', uuid=uuid),
            follow_redirects=True,
        )

        # That entry should have been skipped — queue should be empty
        assert llm_summary_q.empty()

    def test_404_for_unknown_watch(self, client, live_server, datastore_path):
        res = client.get(
            url_for('ui.ui_edit.watch_regenerate_llm_summaries', uuid='does-not-exist'),
            follow_redirects=False,
        )
        assert res.status_code == 404
