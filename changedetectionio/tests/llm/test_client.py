#!/usr/bin/env python3
"""
Tests for changedetectionio.llm.client.completion() and the OrcaRouter
(named OpenAI-compatible routing gateway) model handling.

OrcaRouter model ids are stored as 'orcarouter/<router-id>' where the router id is
itself provider-prefixed (openai/gpt-4o, anthropic/claude-…). litellm keys the
provider off the first path segment, so client.completion() rewrites
'orcarouter/<id>' to 'openai/<id>' before the litellm call — litellm then strips the
leading 'openai/' it recognised itself and sends the full router id on the wire.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from changedetectionio.llm.client import completion


def _fake_response(text='pong'):
    usage = SimpleNamespace(prompt_tokens=3, completion_tokens=1, total_tokens=4)
    message = SimpleNamespace(content=text, parts=None)
    choice = SimpleNamespace(message=message, finish_reason='stop')
    return SimpleNamespace(choices=[choice], usage=usage)


@pytest.mark.parametrize(
    'stored_model,expected_litellm_model',
    [
        ('orcarouter/openai/gpt-4o', 'openai/openai/gpt-4o'),
        ('orcarouter/anthropic/claude-sonnet-4.6', 'openai/anthropic/claude-sonnet-4.6'),
        ('orcarouter/auto', 'openai/auto'),
        ('orcarouter/openai/o3', 'openai/openai/o3'),
    ],
)
def test_completion_rewrites_orcarouter_model(stored_model, expected_litellm_model):
    """OrcaRouter ids must be rewritten to the openai provider so litellm can
    route them, keeping api_base/api_key intact for the gateway."""
    with patch('litellm.completion', return_value=_fake_response()) as mock_llm:
        text, total_tokens, in_tokens, out_tokens = completion(
            model=stored_model,
            messages=[{'role': 'user', 'content': 'hi'}],
            api_key='sk-orca-test',
            api_base='https://api.orcarouter.ai/v1',
        )

    kwargs = mock_llm.call_args.kwargs
    assert kwargs['model'] == expected_litellm_model
    assert kwargs['api_base'] == 'https://api.orcarouter.ai/v1'
    assert kwargs['api_key'] == 'sk-orca-test'

    assert text == 'pong'
    assert (total_tokens, in_tokens, out_tokens) == (4, 3, 1)


def test_completion_leaves_non_orcarouter_models_unchanged():
    """Providers litellm already understands must not be touched."""
    with patch('litellm.completion', return_value=_fake_response()) as mock_llm:
        completion(
            model='openai/gpt-4o',
            messages=[{'role': 'user', 'content': 'hi'}],
            api_key='sk-test',
        )

    assert mock_llm.call_args.kwargs['model'] == 'openai/gpt-4o'


def test_llm_models_endpoint_orcarouter(client, live_server, datastore_path, monkeypatch):
    """GET /settings/llm/models?provider=orcarouter must list the gateway's router
    ids under the orcarouter/ prefix, routed through litellm's openai provider
    against the OrcaRouter api_base."""
    import litellm

    calls = {}

    def fake_get_valid_models(**kwargs):
        calls.update(kwargs)
        return ['openai/gpt-4o', 'anthropic/claude-sonnet-4.6']

    monkeypatch.setattr(litellm, 'get_valid_models', fake_get_valid_models)

    res = client.get(
        __import__('flask').url_for('settings.llm.llm_get_models'),
        query_string={
            'provider': 'orcarouter',
            'api_base': 'https://api.orcarouter.ai/v1',
            'api_key': 'sk-orca-test',
        },
    )

    assert res.status_code == 200
    body = res.get_json()
    assert body['error'] is None
    assert body['models'] == [
        'orcarouter/anthropic/claude-sonnet-4.6',
        'orcarouter/openai/gpt-4o',
    ]
    # Routed through litellm's openai provider (OpenAI wire format) to the gateway.
    assert calls['custom_llm_provider'] == 'openai'
    assert calls['api_base'] == 'https://api.orcarouter.ai/v1'
    assert calls['api_key'] == 'sk-orca-test'
