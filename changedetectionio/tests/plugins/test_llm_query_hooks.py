"""Tests for llm_query_alter and llm_query_finalize pluggy hooks."""
import pytest

from changedetectionio.pluggy_interface import hookimpl, plugin_manager


class _AlterPlugin:
    @hookimpl
    def llm_query_alter(self, llm_context):
        messages = list(llm_context.get('messages') or [])
        if messages:
            messages[-1] = dict(messages[-1])
            messages[-1]['content'] = (messages[-1].get('content') or '') + ' [altered]'
        return {'messages': messages, 'max_tokens': 99}


class _FinalizePlugin:
    def __init__(self):
        self.calls = []

    @hookimpl
    def llm_query_finalize(self, llm_context, result, error):
        self.calls.append({
            'purpose': llm_context.get('purpose'),
            'app_guid': llm_context.get('app_guid'),
            'watch_uuid': llm_context.get('watch_uuid'),
            'result': result,
            'error': error,
        })


@pytest.fixture
def alter_plugin():
    plugin_manager.register(_AlterPlugin(), name='test_llm_alter')
    yield
    plugin_manager.unregister(name='test_llm_alter')


@pytest.fixture
def finalize_plugin():
    plugin = _FinalizePlugin()
    plugin_manager.register(plugin, name='test_llm_finalize')
    yield plugin
    plugin_manager.unregister(name='test_llm_finalize')


def test_llm_query_alter_modifies_messages(client, live_server, measure_memory_usage, datastore_path, alter_plugin, monkeypatch):
    from changedetectionio.llm import invocation as inv

    captured = {}

    def fake_completion(**kwargs):
        captured.update(kwargs)
        return 'ok', 10, 6, 4, {'finish_reason': 'stop'}

    monkeypatch.setattr(inv.llm_client, 'completion', fake_completion)

    ds = client.application.config.get('DATASTORE')
    uuid = ds.add_watch(url='http://example.com', extras={'title': 'Hook test'})
    watch = ds.data['watching'][uuid]

    text, total, inp, out = inv.llm_completion(
        'test_purpose',
        watch=watch,
        datastore=ds,
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': 'hello'}],
    )

    assert text == 'ok'
    assert total == 10
    assert '[altered]' in captured['messages'][-1]['content']
    assert captured['max_tokens'] == 99


def test_llm_query_finalize_receives_context_and_result(
        client, live_server, measure_memory_usage, datastore_path, finalize_plugin, monkeypatch):
    from changedetectionio.llm import invocation as inv

    def fake_completion(**kwargs):
        return 'done', 42, 30, 12, {
            'finish_reason': 'stop',
            'litellm_response_cost_usd': 0.00123,
        }

    monkeypatch.setattr(inv.llm_client, 'completion', fake_completion)

    ds = client.application.config.get('DATASTORE')
    uuid = ds.add_watch(url='http://example.com', extras={'title': 'Finalize test'})
    watch = ds.data['watching'][uuid]
    app_guid = ds.data.get('app_guid')

    inv.llm_completion(
        'evaluate_change',
        watch=watch,
        datastore=ds,
        model='gpt-4o-mini',
        messages=[{'role': 'user', 'content': 'ping'}],
    )

    assert len(finalize_plugin.calls) == 1
    call = finalize_plugin.calls[0]
    assert call['purpose'] == 'evaluate_change'
    assert call['app_guid'] == app_guid
    assert call['watch_uuid'] == uuid
    assert call['error'] is None
    assert call['result']['total_tokens'] == 42
    assert call['result']['input_tokens'] == 30
    assert call['result']['output_tokens'] == 12
    assert call['result']['cost_usd'] > 0
    assert call['result']['litellm_response_cost_usd'] == 0.00123


def test_llm_query_finalize_on_error(
        client, live_server, measure_memory_usage, datastore_path, finalize_plugin, monkeypatch):
    from changedetectionio.llm import invocation as inv

    def fake_completion(**kwargs):
        raise RuntimeError('provider down')

    monkeypatch.setattr(inv.llm_client, 'completion', fake_completion)

    ds = client.application.config.get('DATASTORE')

    with pytest.raises(RuntimeError, match='provider down'):
        inv.llm_completion(
            'connection_test',
            watch=None,
            datastore=ds,
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': 'x'}],
        )

    assert len(finalize_plugin.calls) == 1
    assert finalize_plugin.calls[0]['result'] is None
    assert str(finalize_plugin.calls[0]['error']) == 'provider down'
