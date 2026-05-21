"""
Central LLM invocation path with pluggy hooks.

All production litellm calls should go through llm_completion() so external plugins
can alter requests (llm_query_alter) and record usage afterward (llm_query_finalize).
"""

import time
from copy import deepcopy
from datetime import datetime, timezone

from loguru import logger

from changedetectionio.pluggy_interface import apply_llm_query_alter, apply_llm_query_finalize

from . import client as llm_client


def build_llm_context(
    purpose: str,
    *,
    watch=None,
    datastore=None,
    model: str,
    messages: list,
    api_key: str = None,
    api_base: str = None,
    timeout: int = None,
    max_tokens: int = None,
    extra_body: dict = None,
    debug: bool = False,
) -> dict:
    """Build the context dict for llm_query_alter / llm_query_finalize.

    See ChangeDetectionSpec.llm_query_finalize in pluggy_interface.py for the
    full field reference (purpose, app_guid, watch_uuid, settings, result keys, …).
    """
    app_guid = None
    settings = None
    if datastore is not None:
        try:
            app_guid = datastore.data.get('app_guid')
            settings = deepcopy(datastore.data.get('settings') or {})
        except Exception:
            pass

    watch_uuid = None
    if watch is not None:
        watch_uuid = watch.get('uuid') if isinstance(watch, dict) else getattr(watch, 'uuid', None)

    return {
        'purpose': purpose,
        'watch': watch,
        'datastore': datastore,
        'app_guid': app_guid,
        'watch_uuid': watch_uuid,
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'settings': settings,
        'model': model,
        'messages': messages,
        'api_key': api_key,
        'api_base': api_base,
        'timeout': timeout,
        'max_tokens': max_tokens,
        'extra_body': extra_body,
        'debug': debug,
    }


def _completion_cost_usd(model: str, input_tokens: int, output_tokens: int, metadata: dict) -> float:
    """Prefer litellm's response cost when present, else use the app's pricing estimate."""
    litellm_cost = (metadata or {}).get('litellm_response_cost_usd')
    if litellm_cost is not None:
        try:
            return float(litellm_cost)
        except (TypeError, ValueError):
            pass
    from changedetectionio.llm.evaluator import _estimate_cost_usd
    return _estimate_cost_usd(model, input_tokens, output_tokens)


def llm_completion(
    purpose: str,
    *,
    watch=None,
    datastore=None,
    model: str,
    messages: list,
    api_key: str = None,
    api_base: str = None,
    timeout: int = None,
    max_tokens: int = None,
    extra_body: dict = None,
    debug: bool = False,
) -> tuple[str, int, int, int]:
    """
    Run litellm.completion with pluggy alter/finalize hooks.

    Returns (response_text, total_tokens, input_tokens, output_tokens) — same as
    llm.client.completion for drop-in replacement at call sites.
    """
    llm_context = build_llm_context(
        purpose,
        watch=watch,
        datastore=datastore,
        model=model,
        messages=messages,
        api_key=api_key,
        api_base=api_base,
        timeout=timeout,
        max_tokens=max_tokens,
        extra_body=extra_body,
        debug=debug,
    )
    llm_context = apply_llm_query_alter(llm_context)

    started = time.monotonic()
    result = None
    error = None
    try:
        text, total_tokens, input_tokens, output_tokens, metadata = llm_client.completion(
            model=llm_context['model'],
            messages=llm_context['messages'],
            api_key=llm_context.get('api_key'),
            api_base=llm_context.get('api_base'),
            timeout=llm_context.get('timeout'),
            max_tokens=llm_context.get('max_tokens'),
            extra_body=llm_context.get('extra_body'),
            debug=bool(llm_context.get('debug')),
            return_metadata=True,
        )
        cost_usd = _completion_cost_usd(
            llm_context['model'], input_tokens, output_tokens, metadata,
        )
        result = {
            'text': text,
            'total_tokens': total_tokens,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'cost_usd': cost_usd,
            'litellm_response_cost_usd': (metadata or {}).get('litellm_response_cost_usd'),
            'model': llm_context['model'],
            'finish_reason': (metadata or {}).get('finish_reason'),
            'duration_seconds': time.monotonic() - started,
        }
        return text, total_tokens, input_tokens, output_tokens
    except Exception as e:
        error = e
        raise
    finally:
        apply_llm_query_finalize(llm_context, result, error)
