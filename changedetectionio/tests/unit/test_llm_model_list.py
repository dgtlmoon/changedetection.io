"""
The "Load available models" button must not import litellm (~200MB RSS that is never
released), so a hosted user can explore the AI settings without paying for it.
"""
import os
import subprocess
import sys

import pytest

from changedetectionio.llm import model_list
from changedetectionio.llm.model_list import ModelListError, list_models


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    import requests
    calls = []
    state = {'response': _FakeResponse(payload={})}

    def _get(url, headers=None, timeout=None, allow_redirects=True):
        calls.append({'url': url, 'headers': headers or {}, 'allow_redirects': allow_redirects})
        return state['response']

    monkeypatch.setattr(requests, 'get', _get)
    state['calls'] = calls
    return state


def test_openai_lists_ids_unprefixed(fake_get):
    fake_get['response'] = _FakeResponse(payload={'data': [{'id': 'gpt-4o'}, {'id': 'gpt-4o-mini'}, {'id': 'gpt-4o'}]})
    assert list_models('openai', api_key='sk-1') == ['gpt-4o', 'gpt-4o-mini']
    call = fake_get['calls'][0]
    assert call['url'] == 'https://api.openai.com/v1/models'
    assert call['headers']['Authorization'] == 'Bearer sk-1'
    assert call['allow_redirects'] is False, "a redirect could carry the key to another host"


@pytest.mark.parametrize('api_base, expected', [
    ('http://vllm.example:8000', 'http://vllm.example:8000/v1/models'),
    ('http://vllm.example:8000/v1', 'http://vllm.example:8000/v1/models'),
    ('http://vllm.example:8000/v1/', 'http://vllm.example:8000/v1/models'),
    ('http://gw.example/llm/v1', 'http://gw.example/llm/v1/models'),
])
def test_openai_compatible_url_and_prefix(fake_get, api_base, expected):
    fake_get['response'] = _FakeResponse(payload={'data': [{'id': 'qwen3'}]})
    assert list_models('openai_compatible', api_base=api_base) == ['openai/qwen3']
    assert fake_get['calls'][0]['url'] == expected
    assert 'Authorization' not in fake_get['calls'][0]['headers']


def test_anthropic(fake_get):
    fake_get['response'] = _FakeResponse(payload={'data': [{'id': 'claude-haiku-5-5'}]})
    assert list_models('anthropic', api_key='ak') == ['anthropic/claude-haiku-5-5']
    call = fake_get['calls'][0]
    assert call['url'].startswith('https://api.anthropic.com/v1/models')
    assert call['headers']['x-api-key'] == 'ak'
    assert call['headers']['anthropic-version']


def test_gemini(fake_get):
    fake_get['response'] = _FakeResponse(payload={'models': [{'name': 'models/gemini-2.5-flash'}]})
    assert list_models('gemini', api_key='gk') == ['gemini/gemini-2.5-flash']
    assert fake_get['calls'][0]['headers']['x-goog-api-key'] == 'gk'


@pytest.mark.parametrize('provider', ['anthropic', 'gemini'])
def test_key_required(fake_get, provider):
    with pytest.raises(ModelListError):
        list_models(provider)
    assert fake_get['calls'] == []


@pytest.mark.parametrize('api_base', ['http://ollama.example:11434', 'http://ollama.example:11434/api/chat'])
def test_ollama(fake_get, api_base):
    fake_get['response'] = _FakeResponse(payload={'models': [{'name': 'llama3.2:latest'}, {'model': 'qwen3'}]})
    assert list_models('ollama', api_base=api_base) == ['ollama/llama3.2:latest', 'ollama/qwen3']
    assert fake_get['calls'][0]['url'] == 'http://ollama.example:11434/api/tags'


def test_openrouter(fake_get):
    fake_get['response'] = _FakeResponse(payload={'data': [{'id': 'meta-llama/llama-3-8b'}]})
    assert list_models('openrouter') == ['openrouter/meta-llama/llama-3-8b']
    assert fake_get['calls'][0]['url'] == 'https://openrouter.ai/api/v1/models'


@pytest.mark.parametrize('payload, text, expected', [
    ({'error': {'message': 'Incorrect API key provided'}}, '', 'Incorrect API key provided'),
    ({'error': 'model runner offline'}, '', 'model runner offline'),
    (None, 'Bad Gateway', 'HTTP 502: Bad Gateway'),
])
def test_provider_error_is_surfaced(fake_get, payload, text, expected):
    fake_get['response'] = _FakeResponse(status_code=502 if payload is None else 401, payload=payload, text=text)
    with pytest.raises(ModelListError, match=expected):
        list_models('openai', api_key='bad')


def test_connection_error(monkeypatch):
    import requests

    def _boom(*a, **kw):
        raise requests.exceptions.ConnectionError("refused")

    monkeypatch.setattr(requests, 'get', _boom)
    with pytest.raises(ModelListError, match='Could not connect to ollama.example'):
        list_models('ollama', api_base='http://ollama.example:11434')


def test_unknown_provider():
    with pytest.raises(ModelListError):
        list_models('nope')


def test_listing_models_does_not_import_litellm():
    # Fresh interpreter: litellm is likely already imported in the pytest process
    code = (
        "import sys, requests\n"
        "class R:\n"
        "    status_code = 200\n"
        "    text = ''\n"
        "    def json(self): return {'data': [{'id': 'gpt-4o'}]}\n"
        "requests.get = lambda *a, **kw: R()\n"
        "from changedetectionio.blueprint.settings import llm\n"
        "from changedetectionio.llm.model_list import list_models\n"
        "assert list_models('openai', api_key='k') == ['gpt-4o']\n"
        "assert 'litellm' not in sys.modules, 'litellm was imported'\n"
    )
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(model_list.__file__))))
    env = dict(os.environ, PYTHONPATH=repo_root + os.pathsep + os.environ.get('PYTHONPATH', ''))
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
