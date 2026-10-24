"""
List the models a provider offers, for the "Load available models" button in settings.

Deliberately does NOT use litellm. `import litellm` costs ~200MB RSS that is never given
back, and litellm.get_valid_models() is only a GET against the provider's models endpoint
anyway. Doing that GET ourselves means someone can explore the AI settings tab (pick a
provider, paste a key, browse the model list) without the process paying for litellm.
It is only imported once a model is actually saved and used, or "Test connection" is hit.

Model names are returned in the same form litellm.get_valid_models() produced, so the
string the user picks is still what litellm.completion() expects.
"""

import json
from urllib.parse import urlparse

from loguru import logger

DEFAULT_TIMEOUT = 20

_OPENAI_BASE = 'https://api.openai.com'
_ANTHROPIC_BASE = 'https://api.anthropic.com'
_GEMINI_BASE = 'https://generativelanguage.googleapis.com'
_OLLAMA_BASE = 'http://localhost:11434'
_OPENROUTER_BASE = 'https://openrouter.ai'

# Endpoint suffixes people paste into the Ollama base URL, stripped back to the server root
_OLLAMA_SUFFIXES = ('/api/generate', '/api/chat', '/api/embed', '/api/embeddings', '/api/show', '/api/tags', '/api')


class ModelListError(Exception):
    """The provider refused or could not be reached; str() is safe to show the user."""


def _provider_error_message(response) -> str:
    # Providers wrap the reason differently: OpenAI/Anthropic/Gemini use
    # {"error": {"message": ...}}, Ollama and some proxies {"error": "..."} or {"message": ...}
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        err = body.get('error')
        if isinstance(err, dict) and err.get('message'):
            return str(err['message'])
        if isinstance(err, str) and err:
            return err
        if body.get('message'):
            return str(body['message'])
    text = (response.text or '').strip()
    return f"HTTP {response.status_code}" + (f": {text[:300]}" if text else '')


def _get_json(url, headers, timeout):
    import requests

    logger.debug(f"LLM model list: GET {url}")
    try:
        # No redirects: api_base has already passed the SSRF check, a redirect must not
        # be able to bounce the request (and its Authorization header) somewhere else.
        response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
    except requests.exceptions.RequestException as e:
        raise ModelListError(f"Could not connect to {urlparse(url).netloc}: {e.__class__.__name__}") from e

    if response.status_code != 200:
        raise ModelListError(_provider_error_message(response))
    try:
        return response.json()
    except ValueError as e:
        raise ModelListError(f"Provider returned a non-JSON response from {url}") from e


def _openai_models_url(api_base):
    # Accept both "https://host" and "https://host/v1" (how vLLM / LM Studio usually
    # document it), and keep any path prefix for servers mounted below the root.
    base = (api_base or _OPENAI_BASE).rstrip('/')
    return f"{base}/models" if base.endswith('/v1') else f"{base}/v1/models"


def _ollama_base(api_base):
    base = (api_base or _OLLAMA_BASE).rstrip('/')
    for suffix in _OLLAMA_SUFFIXES:
        if base.endswith(suffix):
            return base[:-len(suffix)]
    return base


def list_models(provider, api_key=None, api_base=None, timeout=DEFAULT_TIMEOUT):
    """Return the sorted model names for `provider` (the UI dropdown value).

    Raises ModelListError with a user-presentable message on any failure.
    """
    api_key = api_key or None
    api_base = api_base or None

    if provider in ('openai', 'openai_compatible'):
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        data = _get_json(_openai_models_url(api_base), headers, timeout)
        # Self-hosted servers speak OpenAI's wire format, litellm routes them via 'openai/'
        prefix = 'openai/' if provider == 'openai_compatible' else ''
        names = [prefix + m['id'] for m in (data.get('data') or []) if m.get('id')]

    elif provider == 'anthropic':
        if not api_key:
            raise ModelListError("An API key is required to list Anthropic models.")
        headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01'}
        base = (api_base or _ANTHROPIC_BASE).rstrip('/')
        # Paginated, 1000 is the maximum page size and well above the current catalogue
        data = _get_json(f"{base}/v1/models?limit=1000", headers, timeout)
        names = ['anthropic/' + m['id'] for m in (data.get('data') or []) if m.get('id')]

    elif provider == 'gemini':
        if not api_key:
            raise ModelListError("An API key is required to list Gemini models.")
        base = (api_base or _GEMINI_BASE).rstrip('/')
        data = _get_json(f"{base}/v1beta/models?pageSize=1000", {'x-goog-api-key': api_key}, timeout)
        names = ['gemini/' + m['name'].replace('models/', '', 1) for m in (data.get('models') or []) if m.get('name')]

    elif provider == 'ollama':
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        data = _get_json(f"{_ollama_base(api_base)}/api/tags", headers, timeout)
        entries = data.get('models') if isinstance(data, dict) else data
        names = []
        for m in entries or []:
            name = isinstance(m, dict) and (m.get('name') or m.get('model'))
            if name:
                names.append(name if name.startswith('ollama/') else f'ollama/{name}')

    elif provider == 'openrouter':
        # Public endpoint, the key is optional and only sent if given
        headers = {'Authorization': f'Bearer {api_key}'} if api_key else {}
        base = (api_base or _OPENROUTER_BASE).rstrip('/')
        url = f"{base}/models" if base.endswith('/api/v1') else f"{base}/api/v1/models"
        data = _get_json(url, headers, timeout)
        names = ['openrouter/' + m['id'] for m in (data.get('data') or []) if m.get('id')]

    else:
        raise ModelListError(f"Unknown provider '{provider}'")

    return sorted(set(names))
