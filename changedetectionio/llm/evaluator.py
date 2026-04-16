"""
LLM evaluation orchestration.

Two public entry points:
  - run_setup(watch, datastore)        — one-time: decide if pre-filter needed
  - evaluate_change(watch, datastore, diff, current_snapshot) — per-change evaluation

Intent resolution: watch.llm_intent → first tag with llm_intent → None (no evaluation)
Cache: each (intent, diff) pair is evaluated exactly once, result stored in watch.

Environment variable overrides (take priority over datastore settings):
  LLM_MODEL    — model string (e.g. "gpt-4o-mini", "ollama/llama3.2")
  LLM_API_KEY  — API key for cloud providers
  LLM_API_BASE — base URL for local/custom endpoints (e.g. http://localhost:11434)
"""

import hashlib
import os
from loguru import logger

from . import client as llm_client
from .prompt_builder import (
    build_change_summary_prompt, build_change_summary_system_prompt,
    build_eval_prompt, build_eval_system_prompt,
    build_preview_prompt, build_preview_system_prompt,
    build_setup_prompt, build_setup_system_prompt,
)
from .response_parser import parse_eval_response, parse_preview_response, parse_setup_response

# AI Change Summary can produce longer output than eval responses
_MAX_SUMMARY_TOKENS = 500

# Default prompt used when the user hasn't configured llm_change_summary
DEFAULT_CHANGE_SUMMARY_PROMPT = "Briefly describe in plain English what changed — what was added, removed, or modified."


# ---------------------------------------------------------------------------
# Intent resolution
# ---------------------------------------------------------------------------

def resolve_llm_field(watch, datastore, field: str) -> tuple[str, str]:
    """
    Generic cascade resolver for any LLM per-watch field.
    Returns (value, source) where source is 'watch' or tag title.
    Returns ('', '') if not set anywhere.
    """
    value = (watch.get(field) or '').strip()
    if value:
        return value, 'watch'

    for tag_uuid in watch.get('tags', []):
        tag = datastore.data['settings']['application'].get('tags', {}).get(tag_uuid)
        if tag:
            tag_value = (tag.get(field) or '').strip()
            if tag_value:
                return tag_value, tag.get('title', 'tag')

    return '', ''


def resolve_intent(watch, datastore) -> tuple[str, str]:
    """
    Return (intent, source) where source is 'watch' or tag title.
    Returns ('', '') if no intent is configured anywhere.
    """
    intent = (watch.get('llm_intent') or '').strip()
    if intent:
        return intent, 'watch'

    for tag_uuid in watch.get('tags', []):
        tag = datastore.data['settings']['application'].get('tags', {}).get(tag_uuid)
        if tag:
            tag_intent = (tag.get('llm_intent') or '').strip()
            if tag_intent:
                return tag_intent, tag.get('title', 'tag')

    return '', ''


# ---------------------------------------------------------------------------
# LLM config helper
# ---------------------------------------------------------------------------

def get_llm_config(datastore) -> dict | None:
    """
    Return LLM config dict or None if not configured.

    Resolution order (first non-empty model wins):
      1. Environment variables: LLM_MODEL, LLM_API_KEY, LLM_API_BASE
      2. Datastore settings (set via UI)
    """
    # 1. Environment variable override
    env_model = os.getenv('LLM_MODEL', '').strip()
    if env_model:
        return {
            'model': env_model,
            'api_key': os.getenv('LLM_API_KEY', '').strip(),
            'api_base': os.getenv('LLM_API_BASE', '').strip(),
        }

    # 2. Datastore settings
    cfg = datastore.data['settings']['application'].get('llm') or {}
    if not cfg.get('model'):
        return None
    return cfg


def llm_configured_via_env() -> bool:
    """True when LLM config comes from environment variables, not the UI."""
    return bool(os.getenv('LLM_MODEL', '').strip())


# ---------------------------------------------------------------------------
# One-time setup: derive pre-filter
# ---------------------------------------------------------------------------

def _check_token_budget(watch, cfg, tokens_this_call: int = 0) -> bool:
    """
    Check token budget limits.  Returns True if within budget, False if exceeded.
    Also accumulates tokens_this_call into watch['llm_tokens_used_cumulative'].
    """
    if tokens_this_call > 0:
        current = watch.get('llm_tokens_used_cumulative') or 0
        watch['llm_tokens_used_cumulative'] = current + tokens_this_call

    max_per_check = int(cfg.get('max_tokens_per_check') or 0)
    max_cumulative = int(cfg.get('max_tokens_cumulative') or 0)

    if max_per_check and tokens_this_call > max_per_check:
        logger.warning(
            f"LLM token budget exceeded for {watch.get('uuid')}: "
            f"{tokens_this_call} tokens > per-check limit {max_per_check}"
        )
        return False

    if max_cumulative:
        total = watch.get('llm_tokens_used_cumulative') or 0
        if total > max_cumulative:
            logger.warning(
                f"LLM cumulative token budget exceeded for {watch.get('uuid')}: "
                f"{total} tokens > limit {max_cumulative}"
            )
            return False

    return True


def run_setup(watch, datastore, snapshot_text: str) -> None:
    """
    Ask the LLM whether a CSS pre-filter would improve precision for this intent.
    Stores result in watch['llm_prefilter'] (str selector or None).
    Called once when intent is first set, and again if pre-filter returns zero matches.
    """
    cfg = get_llm_config(datastore)
    if not cfg:
        return

    intent, _ = resolve_intent(watch, datastore)
    if not intent:
        return

    url = watch.get('url', '')
    system_prompt = build_setup_system_prompt()
    user_prompt = build_setup_prompt(intent, snapshot_text, url=url)

    try:
        raw, tokens = llm_client.completion(
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
        )
        _check_token_budget(watch, cfg, tokens)
        result = parse_setup_response(raw)
        watch['llm_prefilter'] = result['selector']
        logger.debug(f"LLM setup for {watch.get('uuid')}: prefilter={result['selector']} reason={result['reason']}")
    except Exception as e:
        logger.warning(f"LLM setup call failed for {watch.get('uuid')}: {e}")
        watch['llm_prefilter'] = None


# ---------------------------------------------------------------------------
# AI Change Summary — human-readable description of what changed
# ---------------------------------------------------------------------------

def get_effective_summary_prompt(watch, datastore) -> str:
    """Return the prompt that summarise_change will use — custom or the default fallback."""
    prompt, _ = resolve_llm_field(watch, datastore, 'llm_change_summary')
    return prompt or DEFAULT_CHANGE_SUMMARY_PROMPT


def compute_summary_cache_key(diff_text: str, prompt: str) -> str:
    """Stable 16-char hex key for a (diff, prompt) pair.  Stored alongside the summary file."""
    h = hashlib.md5()
    h.update(diff_text.encode('utf-8', errors='replace'))
    h.update(b'\x00')
    h.update(prompt.encode('utf-8', errors='replace'))
    return h.hexdigest()[:16]


def summarise_change(watch, datastore, diff: str, current_snapshot: str = '') -> str:
    """
    Generate a plain-language summary of the change using the watch's
    llm_change_summary prompt (cascades from tag if not set on watch).

    Returns the summary string, or '' on failure.
    The result replaces {{ diff }} in notifications so the user gets a
    readable description instead of raw +/- diff lines.
    """
    cfg = get_llm_config(datastore)
    if not cfg:
        return ''

    custom_prompt, _ = resolve_llm_field(watch, datastore, 'llm_change_summary')
    if not custom_prompt:
        custom_prompt = DEFAULT_CHANGE_SUMMARY_PROMPT
    if not diff.strip():
        return ''

    url = watch.get('url', '')
    title = watch.get('page_title') or watch.get('title') or ''

    system_prompt = build_change_summary_system_prompt()
    user_prompt = build_change_summary_prompt(
        diff=diff,
        custom_prompt=custom_prompt,
        current_snapshot=current_snapshot,
        url=url,
        title=title,
    )

    try:
        raw, tokens = llm_client.completion(
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
            max_tokens=_MAX_SUMMARY_TOKENS,
        )
        summary = raw.strip()
        _check_token_budget(watch, cfg, tokens)
        watch['llm_last_tokens_used'] = (watch.get('llm_last_tokens_used') or 0) + tokens
        logger.debug(
            f"LLM change summary {watch.get('uuid')}: tokens={tokens} "
            f"summary={summary[:80]}"
        )
        return summary
    except Exception as e:
        logger.warning(f"LLM change summary failed for {watch.get('uuid')}: {e}")
        return ''


# ---------------------------------------------------------------------------
# Live-preview extraction (current content, no diff)
# ---------------------------------------------------------------------------

def preview_extract(watch, datastore, content: str) -> dict | None:
    """
    For the live-preview endpoint: extract relevant information from the
    *current* page content according to the watch's intent.

    Unlike evaluate_change (which compares a diff), this asks the LLM to
    directly answer the intent against the current snapshot — giving the user
    immediate feedback like "30 articles listed" or "Price: $149, 25% off".

    Returns {'found': bool, 'answer': str} or None if LLM not configured / no intent.
    """
    cfg = get_llm_config(datastore)
    if not cfg:
        return None

    intent, _ = resolve_intent(watch, datastore)
    if not intent or not content.strip():
        return None

    url = watch.get('url', '')
    title = watch.get('page_title') or watch.get('title') or ''

    system_prompt = build_preview_system_prompt()
    user_prompt = build_preview_prompt(intent, content, url=url, title=title)

    try:
        raw, tokens = llm_client.completion(
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
        )
        result = parse_preview_response(raw)
        logger.debug(
            f"LLM preview {watch.get('uuid')}: found={result['found']} "
            f"tokens={tokens} answer={result['answer'][:80]}"
        )
        return result
    except Exception as e:
        logger.warning(f"LLM preview extraction failed for {watch.get('uuid')}: {e}")
        return None


# ---------------------------------------------------------------------------
# Per-change evaluation
# ---------------------------------------------------------------------------

def evaluate_change(watch, datastore, diff: str, current_snapshot: str = '') -> dict | None:
    """
    Evaluate whether `diff` matches the watch's intent.
    Returns {'important': bool, 'summary': str} or None if LLM not configured / no intent.

    Results are cached by (intent, diff) hash — each unique diff is evaluated exactly once.
    """
    cfg = get_llm_config(datastore)
    if not cfg:
        return None

    intent, source = resolve_intent(watch, datastore)
    if not intent:
        return None

    if not diff or not diff.strip():
        return {'important': False, 'summary': ''}

    # Cache lookup — evaluations are deterministic once cached
    cache_key = hashlib.sha256(f"{intent}||{diff}".encode()).hexdigest()
    cache = watch.get('llm_evaluation_cache') or {}
    if cache_key in cache:
        logger.debug(f"LLM cache hit for {watch.get('uuid')} key={cache_key[:8]}")
        return cache[cache_key]

    # Check cumulative budget before making the call
    if not _check_token_budget(watch, cfg):
        # Already over budget — fail open (don't suppress notification)
        return {'important': True, 'summary': ''}

    url = watch.get('url', '')
    title = watch.get('page_title') or watch.get('title') or ''

    system_prompt = build_eval_system_prompt()
    user_prompt = build_eval_prompt(
        intent=intent,
        diff=diff,
        current_snapshot=current_snapshot,
        url=url,
        title=title,
    )

    try:
        raw, tokens = llm_client.completion(
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
        )
        result = parse_eval_response(raw)
    except Exception as e:
        logger.warning(f"LLM evaluation failed for {watch.get('uuid')}: {e}")
        # On failure: don't suppress the notification — pass through as important
        watch['llm_last_tokens_used'] = 0
        return {'important': True, 'summary': ''}

    # Accumulate token usage and enforce per-check limit
    _check_token_budget(watch, cfg, tokens)
    watch['llm_last_tokens_used'] = tokens

    # Store in cache
    if 'llm_evaluation_cache' not in watch or watch['llm_evaluation_cache'] is None:
        watch['llm_evaluation_cache'] = {}
    watch['llm_evaluation_cache'][cache_key] = result

    logger.debug(
        f"LLM eval {watch.get('uuid')} (intent from {source}): "
        f"important={result['important']} tokens={tokens} summary={result['summary'][:80]}"
    )
    return result
