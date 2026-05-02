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
from datetime import datetime, timezone
from loguru import logger

from . import client as llm_client
from .prompt_builder import (
    build_change_summary_prompt, build_change_summary_system_prompt,
    build_eval_prompt, build_eval_system_prompt,
    build_preview_prompt, build_preview_system_prompt,
    build_setup_prompt, build_setup_system_prompt,
)
from .response_parser import parse_eval_response, parse_preview_response, parse_setup_response

_DEFAULT_MAX_INPUT_CHARS = 100_000

def _get_max_input_chars(datastore) -> int:
    """Max input characters to send to the LLM. Resolution: env var → datastore → 100,000.
    Always returns at least 1 — unlimited is not permitted.
    """
    env_val = os.getenv('LLM_MAX_INPUT_CHARS', '').strip()
    if env_val.isdigit() and int(env_val) > 0:
        return int(env_val)
    cfg = datastore.data.get('settings', {}).get('application', {}).get('llm') or {}
    stored = cfg.get('max_input_chars')
    if stored and int(stored) > 0:
        return int(stored)
    return _DEFAULT_MAX_INPUT_CHARS


class LLMInputTooLargeError(Exception):
    pass


def _check_input_size(text: str, max_chars: int) -> None:
    """Raise LLMInputTooLargeError if text exceeds max_chars."""
    if len(text) > max_chars:
        raise LLMInputTooLargeError(
            f"Change too large for AI summary ({len(text):,} chars, limit {max_chars:,})"
        )


LLM_DEFAULT_THINKING_BUDGET = 0  # 0 = thinking disabled by default

def _thinking_extra_body(model: str, budget: int) -> dict | None:
    """Return litellm extra_body to control thinking for models that support it.
    For Gemini 2.5+: passes thinkingConfig with the given budget (0 = disabled).
    For all other models: returns None (no-op).
    """
    if not model.startswith('gemini/gemini-2.5'):
        return None
    return {'generationConfig': {'thinkingConfig': {'thinkingBudget': budget}}}


def _cached_system(text: str, model: str = '') -> dict:
    """Wrap a system prompt, adding Anthropic prompt-caching headers only for Anthropic models.
    Gemini and other providers have their own caching APIs that break when they receive
    cache_control, so we only apply it where it's supported.
    """
    is_anthropic = model.startswith('claude') or model.startswith('anthropic/')
    if is_anthropic:
        return {'role': 'system', 'content': [{'type': 'text', 'text': text, 'cache_control': {'type': 'ephemeral'}}]}
    return {'role': 'system', 'content': text}


LLM_DEFAULT_MAX_SUMMARY_TOKENS = 3000

# Output-token cap for the JSON-returning calls (intent eval, preview, setup/prefilter).
# Mirrors client.py's _MAX_COMPLETION_TOKENS so the multiplier helper has a base value
# to scale; cloud-LLM users hit this default unmodified, preserving prior cost defaults.
JSON_RESPONSE_MAX_TOKENS = 400

# Default prompt used when the user hasn't configured llm_change_summary
DEFAULT_CHANGE_SUMMARY_PROMPT = "Describe in plain English what changed — list what was added or removed as bullet points, including key details for each item. Be careful of content that merely just moved around, you should mention that it moved but dont report that it was added/removed etc. Be considerate of the style content you are summarising the change of, adjust your report accordingly. Do not quote non-English text verbatim; translate and summarise all content into English. Your entire response must be in English."


def _summary_max_tokens(diff: str, max_cap: int = LLM_DEFAULT_MAX_SUMMARY_TOKENS) -> int:
    """Scale completion tokens to diff size: floor 400, ~1 token per 4 chars, ceiling max_cap."""
    return max(400, min(len(diff) // 4, max_cap))


def apply_local_token_multiplier(base_max_tokens: int, llm_cfg: dict) -> int:
    """
    Scale max_tokens for self-hosted OpenAI-compatible endpoints (vLLM, LM Studio, llama.cpp).

    Reasoning models (Qwen3, DeepSeek-R1, Gemma 3, etc.) emit chain-of-thought into
    `message.reasoning_content` BEFORE the final answer lands in `message.content`.
    Without enough headroom the request truncates mid-thought (`finish_reason='length'`)
    and the answer never lands — callers see an empty string and silently fall through
    to safe defaults, hiding the problem.

    Local self-hosted models cost no per-token money, so headroom is cheap; cloud
    providers (OpenAI, Anthropic, Gemini, OpenRouter) keep their original tight caps
    so existing users see no cost change.

    Activated only when `llm_cfg['provider_kind'] == 'openai_compatible'`.
    Multiplier defaults to 5x and is user-configurable in Settings → AI → Provider.
    """
    if (llm_cfg or {}).get('provider_kind') != 'openai_compatible':
        return base_max_tokens
    try:
        multiplier = int(llm_cfg.get('local_token_multiplier') or 5)
    except (TypeError, ValueError):
        multiplier = 5
    # Clamp to the same 1-20 range the form enforces. Defense-in-depth against
    # corrupted datastore values that bypassed form validation (manual JSON edits,
    # future migrations, plugins): a runaway multiplier could otherwise produce
    # absurdly large max_tokens caps and exhaust local-endpoint memory.
    multiplier = max(1, min(multiplier, 20))
    return base_max_tokens * multiplier


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
# Global monthly token budget
# ---------------------------------------------------------------------------

def _get_month_key() -> str:
    """Returns 'YYYY-MM' for the current UTC month."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def get_global_token_budget_month(datastore=None) -> int:
    """
    Monthly token budget ceiling. Resolution order:
      1. LLM_TOKEN_BUDGET_MONTH env var (takes priority, makes field read-only in UI)
      2. datastore settings (set via UI)
    Returns 0 (no limit) if not set anywhere.
    """
    try:
        env_val = int(os.getenv('LLM_TOKEN_BUDGET_MONTH', '0'))
        if env_val > 0:
            return env_val
    except (ValueError, TypeError):
        pass
    if datastore is not None:
        try:
            stored = datastore.data['settings']['application'].get('llm') or {}
            val = int(stored.get('token_budget_month') or 0)
            return max(0, val)
        except (ValueError, TypeError):
            pass
    return 0


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """
    Return estimated cost in USD using litellm's pricing database.
    Returns 0.0 for unknown models (local/Ollama/custom endpoints).
    Never raises — cost estimation is best-effort.
    """
    if not model or (not input_tokens and not output_tokens):
        return 0.0
    try:
        from litellm.cost_calculator import cost_per_token
        prompt_cost, completion_cost = cost_per_token(
            model=model,
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
        )
        return float(prompt_cost + completion_cost)
    except Exception:
        return 0.0


def accumulate_global_tokens(datastore, tokens: int,
                              input_tokens: int = 0, output_tokens: int = 0,
                              model: str = '') -> None:
    """
    Add *tokens* to both the all-time and this-month global counters.
    When input_tokens / output_tokens / model are supplied the estimated
    USD cost is accumulated alongside the token counts.
    Resets monthly counters automatically on month rollover.

    These counters live at datastore.data['settings']['application']['llm']
    and are intentionally read-only from the API/form side — they are only
    ever written here, in a controlled way.
    """
    if tokens <= 0:
        return

    current_month = _get_month_key()
    cost = _estimate_cost_usd(model, input_tokens, output_tokens)

    # Work on the live dict in-place (or create a stub if llm key is absent)
    app_settings = datastore.data['settings']['application']
    if 'llm' not in app_settings:
        app_settings['llm'] = {}
    llm_cfg = app_settings['llm']

    # Month rollover: reset monthly counters
    if llm_cfg.get('tokens_month_key') != current_month:
        llm_cfg['tokens_this_month'] = 0
        llm_cfg['cost_usd_this_month'] = 0.0
        llm_cfg['tokens_month_key'] = current_month

    llm_cfg['tokens_total_cumulative'] = (llm_cfg.get('tokens_total_cumulative') or 0) + tokens
    llm_cfg['tokens_this_month']       = (llm_cfg.get('tokens_this_month') or 0) + tokens
    llm_cfg['cost_usd_total_cumulative'] = (llm_cfg.get('cost_usd_total_cumulative') or 0.0) + cost
    llm_cfg['cost_usd_this_month']       = (llm_cfg.get('cost_usd_this_month') or 0.0) + cost

    # Persist immediately — token accounting must survive restarts
    datastore.commit()


def is_global_token_budget_exceeded(datastore) -> bool:
    """
    Returns True when a monthly token budget is configured (via
    LLM_TOKEN_BUDGET_MONTH) and the current month's usage has reached
    or exceeded that budget.
    """
    budget = get_global_token_budget_month(datastore)
    if not budget:
        return False

    llm_cfg = datastore.data['settings']['application'].get('llm') or {}
    if llm_cfg.get('tokens_month_key') != _get_month_key():
        # Counter hasn't been updated yet this month → zero usage
        return False

    return (llm_cfg.get('tokens_this_month') or 0) >= budget


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
        raw, tokens, *_ = llm_client.completion(
            model=cfg['model'],
            messages=[
                _cached_system(system_prompt, model=cfg['model']),
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
            max_tokens=apply_local_token_multiplier(JSON_RESPONSE_MAX_TOKENS, cfg),
            extra_body=_thinking_extra_body(cfg['model'], int(datastore.data['settings']['application'].get('llm_thinking_budget', LLM_DEFAULT_THINKING_BUDGET) or 0)),
        )
        _check_token_budget(watch, cfg, tokens)
        accumulate_global_tokens(datastore, tokens, model=cfg['model'])
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
    """Return the prompt that summarise_change will use.

    Cascade: watch → tag → global settings default → hardcoded fallback.
    """
    prompt, _ = resolve_llm_field(watch, datastore, 'llm_change_summary')
    if prompt:
        return prompt
    global_default = (
        datastore.data.get('settings', {})
        .get('application', {})
        .get('llm_change_summary_default', '') or ''
    ).strip()
    return global_default or DEFAULT_CHANGE_SUMMARY_PROMPT


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

    if is_global_token_budget_exceeded(datastore):
        budget = get_global_token_budget_month(datastore)
        llm_cfg = datastore.data['settings']['application'].get('llm') or {}
        used = llm_cfg.get('tokens_this_month', 0)
        logger.warning(
            f"LLM summarise_change skipped: monthly budget {budget:,} reached "
            f"({used:,} used this month)"
        )
        return ''

    custom_prompt = get_effective_summary_prompt(watch, datastore)
    if not diff.strip():
        return ''

    _check_input_size(diff, _get_max_input_chars(datastore))
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

    _thinking_budget = int(datastore.data['settings']['application'].get('llm_thinking_budget', LLM_DEFAULT_THINKING_BUDGET) or 0)
    _extra_body = _thinking_extra_body(cfg['model'], _thinking_budget)

    try:
        _resp = llm_client.completion(
            model=cfg['model'],
            messages=[
                _cached_system(system_prompt, model=cfg['model']),
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
            max_tokens=apply_local_token_multiplier(
                _summary_max_tokens(
                    diff,
                    max_cap=int(datastore.data['settings']['application'].get('llm_max_summary_tokens', LLM_DEFAULT_MAX_SUMMARY_TOKENS) or LLM_DEFAULT_MAX_SUMMARY_TOKENS),
                ),
                cfg,
            ),
            extra_body=_extra_body,
        )
        raw, tokens = _resp[0], _resp[1]
        input_tokens  = _resp[2] if len(_resp) > 2 else 0
        output_tokens = _resp[3] if len(_resp) > 3 else 0
        summary = raw.strip()
        _check_token_budget(watch, cfg, tokens)
        watch['llm_last_tokens_used'] = tokens
        watch['llm_tokens_used_cumulative'] = (watch.get('llm_tokens_used_cumulative') or 0) + tokens
        accumulate_global_tokens(datastore, tokens,
                                 input_tokens=input_tokens,
                                 output_tokens=output_tokens,
                                 model=cfg['model'])
        logger.debug(
            f"LLM change summary {watch.get('uuid')}: tokens={tokens} "
            f"summary={summary[:80]}"
        )
        return summary
    except Exception as e:
        raise


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

    _check_input_size(content, _get_max_input_chars(datastore))
    url = watch.get('url', '')
    title = watch.get('page_title') or watch.get('title') or ''

    system_prompt = build_preview_system_prompt()
    user_prompt = build_preview_prompt(intent, content, url=url, title=title)

    try:
        raw, tokens, *_ = llm_client.completion(
            model=cfg['model'],
            messages=[
                _cached_system(system_prompt, model=cfg['model']),
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
            max_tokens=apply_local_token_multiplier(JSON_RESPONSE_MAX_TOKENS, cfg),
            extra_body=_thinking_extra_body(cfg['model'], int(datastore.data['settings']['application'].get('llm_thinking_budget', LLM_DEFAULT_THINKING_BUDGET) or 0)),
        )
        accumulate_global_tokens(datastore, tokens, model=cfg['model'])
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

    _check_input_size(diff, _get_max_input_chars(datastore))

    # Cache lookup — evaluations are deterministic once cached
    cache_key = hashlib.sha256(f"{intent}||{diff}".encode()).hexdigest()
    cache = watch.get('llm_evaluation_cache') or {}
    if cache_key in cache:
        logger.debug(f"LLM cache hit for {watch.get('uuid')} key={cache_key[:8]}")
        return cache[cache_key]

    # Check global monthly budget before making the call
    if is_global_token_budget_exceeded(datastore):
        budget = get_global_token_budget_month(datastore)
        llm_cfg = datastore.data['settings']['application'].get('llm') or {}
        used = llm_cfg.get('tokens_this_month', 0)
        logger.warning(
            f"LLM evaluate_change skipped for {watch.get('uuid')}: monthly budget {budget:,} reached "
            f"({used:,} used this month) — passing change through as important"
        )
        # Fail open: don't suppress notifications when budget is exhausted
        return {'important': True, 'summary': ''}

    # Check per-watch cumulative budget before making the call
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
        _resp = llm_client.completion(
            model=cfg['model'],
            messages=[
                _cached_system(system_prompt, model=cfg['model']),
                {'role': 'user', 'content': user_prompt},
            ],
            api_key=cfg.get('api_key'),
            api_base=cfg.get('api_base'),
            max_tokens=apply_local_token_multiplier(JSON_RESPONSE_MAX_TOKENS, cfg),
            extra_body=_thinking_extra_body(cfg['model'], int(datastore.data['settings']['application'].get('llm_thinking_budget', LLM_DEFAULT_THINKING_BUDGET) or 0)),
        )
        raw, tokens = _resp[0], _resp[1]
        input_tokens  = _resp[2] if len(_resp) > 2 else 0
        output_tokens = _resp[3] if len(_resp) > 3 else 0
        result = parse_eval_response(raw)
    except Exception as e:
        logger.warning(f"LLM evaluation failed for {watch.get('uuid')}: {e}")
        # On failure: don't suppress the notification — pass through as important
        watch['llm_last_tokens_used'] = 0
        return {'important': True, 'summary': ''}

    # Accumulate token usage: per-watch limit and global monthly budget
    _check_token_budget(watch, cfg, tokens)
    watch['llm_last_tokens_used'] = tokens
    accumulate_global_tokens(datastore, tokens,
                             input_tokens=input_tokens,
                             output_tokens=output_tokens,
                             model=cfg['model'])

    # Store in cache
    if 'llm_evaluation_cache' not in watch or watch['llm_evaluation_cache'] is None:
        watch['llm_evaluation_cache'] = {}
    watch['llm_evaluation_cache'][cache_key] = result

    logger.debug(
        f"LLM eval {watch.get('uuid')} (intent from {source}): "
        f"important={result['important']} tokens={tokens} summary={result['summary'][:80]}"
    )
    return result
