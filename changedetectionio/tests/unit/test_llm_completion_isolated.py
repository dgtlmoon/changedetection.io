"""
"Test connection" runs litellm in a throwaway subprocess so trying a provider doesn't
leave ~200MB of litellm resident in the main process.
"""
import multiprocessing
import sys

import pytest

from changedetectionio.llm import client as llm_client


def test_runs_in_process_when_litellm_already_loaded(monkeypatch):
    monkeypatch.setitem(sys.modules, 'litellm', sys.modules.get('litellm') or object())
    monkeypatch.setattr(llm_client, 'completion', lambda **kw: ('ready', 6, 5, 1))

    def _no_spawn(*a, **kw):
        raise AssertionError("must not spawn when litellm is already imported")

    monkeypatch.setattr(multiprocessing, 'get_context', _no_spawn)
    assert llm_client.completion_isolated(model='m', messages=[]) == ('ready', 6, 5, 1)


def _run_worker(monkeypatch, fake_completion, kwargs):
    import json
    monkeypatch.setattr(llm_client, 'completion', fake_completion)
    monkeypatch.setattr(llm_client.logger, 'remove', lambda *a, **kw: None)
    monkeypatch.setattr(llm_client.logger, 'add', lambda *a, **kw: None)
    parent, child = multiprocessing.Pipe()
    parent.send_bytes(json.dumps(kwargs).encode('utf-8'))
    llm_client._completion_worker(child, 'DEBUG')
    return json.loads(parent.recv_bytes().decode('utf-8'))


def test_worker_returns_result(monkeypatch):
    seen = {}

    def fake(**kw):
        seen.update(kw)
        return ('ready', 6, 5, 1)

    out = _run_worker(monkeypatch, fake, {'model': 'openai/m', 'messages': [], 'timeout': 30})
    assert out == {'ok': True, 'result': ['ready', 6, 5, 1]}
    assert seen['model'] == 'openai/m' and seen['timeout'] == 30


def test_worker_returns_error_message(monkeypatch):
    def fake(**kw):
        raise ValueError("Incorrect API key provided")

    out = _run_worker(monkeypatch, fake, {'model': 'm', 'messages': []})
    assert out['ok'] is False
    assert out['error'] == "Incorrect API key provided"


@pytest.mark.skipif(sys.platform != 'linux', reason="subprocess isolation is Linux only")
def test_child_error_is_reraised(monkeypatch):
    # Real spawn: the child can't see monkeypatches, so give it a call that fails fast
    # before any network (unknown provider prefix is rejected by litellm itself)
    monkeypatch.delitem(sys.modules, 'litellm', raising=False)
    with pytest.raises(RuntimeError):
        llm_client.completion_isolated(model='not-a-provider/x', messages=[{'role': 'user', 'content': 'hi'}],
                                       api_key='k', timeout=5)
    assert 'litellm' not in sys.modules
