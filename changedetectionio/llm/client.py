"""
Thin wrapper around litellm.completion.
Keeps litellm import isolated so the rest of the codebase doesn't depend on it directly,
and makes the call easy to mock in tests.
"""

import logging
import os
import re
from loguru import logger

# Default output token cap for JSON-returning calls (intent eval, preview, setup).
# These return small JSON objects — 400 is enough for a verbose explanation while
# still preventing runaway cost. Change summaries pass their own max_tokens via
# _summary_max_tokens() and are NOT subject to this cap.
_MAX_COMPLETION_TOKENS = 400

# Default request timeout (seconds). Raised from 60 to 300 because even cloud
# reasoning models can be slow on the first hit (issue #4225). Overridable via
# LLM_TIMEOUT.
DEFAULT_TIMEOUT = int(os.getenv('LLM_TIMEOUT', 300))
# Relaxed timeout for local / self-hosted endpoints (Ollama, vLLM, LM Studio,
# llama.cpp on localhost or a LAN address). These run on modest hardware and can
# spend many minutes on prompt prefill before the first token, so they get a much
# longer deadline (Hermes-style, 30 min). Overridable via LLM_LOCAL_TIMEOUT; see
# evaluator.resolve_llm_timeout() for how the endpoint is classified.
DEFAULT_LOCAL_TIMEOUT = int(os.getenv('LLM_LOCAL_TIMEOUT', 1800))
DEFAULT_RETRIES = 3

# Matches "gemini-3" with or without a provider prefix (gemini/gemini-3.5-flash-lite,
# vertex_ai/gemini-3-pro-preview, plain "gemini-3-pro-preview", ...).
_GEMINI_3_RE = re.compile(r'gemini-3', re.IGNORECASE)


def is_gemini_3_family(model: str) -> bool:
    """True for any Gemini 3.x model.

    Google's Gemini 3.x migration deprecates the `temperature`/`top_p`/`top_k`
    sampling params and replaces `thinkingConfig.thinkingBudget` with a new
    `thinking_level` control. Sending the old params gets a bare 400
    INVALID_ARGUMENT with no `details` field — litellm's model registry lags
    brand-new releases, so we can't rely on it (or on drop_params) to catch this
    before the request goes out. Gated on the model name directly so the very
    first request avoids the error, rather than depending on the retry path
    below to clean it up after the fact.
    """
    return bool(model) and bool(_GEMINI_3_RE.search(model))


class _LoguruInterceptHandler(logging.Handler):
    # Routes litellm's stdlib log records through loguru so debug output
    # uses the same format/sink as the rest of the app.
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except (ValueError, AttributeError):
            level = record.levelno
        logger.opt(exception=record.exc_info).log(level, record.getMessage())


_debug_installed = False


def _install_litellm_debug():
    # Attach our loguru intercept and clear any pre-existing handlers so litellm's
    # own stdout StreamHandler (installed by _turn_on_debug / set_verbose) doesn't
    # double-emit. Setting the logger level to DEBUG is enough to make litellm
    # produce debug records — we don't call _turn_on_debug() for that reason.
    global _debug_installed
    if _debug_installed:
        return

    handler = _LoguruInterceptHandler()
    handler.setLevel(logging.DEBUG)
    for _name in ('LiteLLM', 'litellm', 'litellm.utils', 'litellm.router'):
        _lg = logging.getLogger(_name)
        _lg.handlers = []
        _lg.setLevel(logging.DEBUG)
        _lg.addHandler(handler)
        _lg.propagate = False

    _debug_installed = True
    logger.info("LLM client: litellm debug logging routed through loguru")


def completion(model: str, messages: list, api_key: str = None,
               api_base: str = None, timeout: int = DEFAULT_TIMEOUT,
               max_tokens: int = None, extra_body: dict = None,
               debug: bool = False) -> tuple[str, int, int, int]:
    """
    Call the LLM and return (response_text, total_tokens, input_tokens, output_tokens).
    Retries up to DEFAULT_RETRIES times on timeout or connection errors.
    Token counts are 0 if the provider doesn't return usage data.
    Raises on network/auth errors — callers handle gracefully.

    timeout: seconds for the request. Local endpoints get a longer value than cloud —
    see evaluator.resolve_llm_timeout().
    """
    try:
        import litellm
    except ImportError:
        raise RuntimeError("litellm is not installed. Add it to requirements.txt.")

    if debug:
        _install_litellm_debug()

    _timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    kwargs = {
        'model': model,
        'messages': messages,
        'timeout': _timeout,
        'max_tokens': max_tokens if max_tokens is not None else _MAX_COMPLETION_TOKENS,
    }
    if not is_gemini_3_family(model):
        # Gemini 3.x rejects 'temperature' outright (see is_gemini_3_family) —
        # every other provider we support accepts temperature=0 fine.
        kwargs['temperature'] = 0
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base
    if extra_body:
        kwargs['extra_body'] = extra_body

    _retryable = (litellm.Timeout, litellm.APIConnectionError)

    # Some models reject sampling params outright: Anthropic Claude Opus 4.7/4.8 and
    # Fable return HTTP 400 for 'temperature', and OpenAI reasoning models (o1/o3/gpt-5)
    # only accept the default. litellm's per-model param metadata lags new releases, so
    # drop_params can't be relied on for freshly released models — instead, if the provider
    # rejects a sampling param, strip them and retry once. Models that accept them are
    # unaffected (they still receive temperature=0).
    _sampling_params = ('temperature', 'top_p', 'top_k')
    _stripped_sampling = False

    logger.debug(
        f"LLM client: calling model={model!r} api_base={api_base!r} "
        f"timeout={_timeout}s max_tokens={kwargs['max_tokens']}"
    )
    logger.trace(messages)

    attempt = 0
    while attempt < DEFAULT_RETRIES:
        attempt += 1
        try:
            response = litellm.completion(**kwargs)
            choice   = response.choices[0]
            message  = choice.message
            finish   = getattr(choice, 'finish_reason', None)

            text = message.content or ''

            if not text:
                # Some providers (e.g. Gemini) put text in message.parts instead of .content
                parts = getattr(message, 'parts', None)
                if parts:
                    text = ''.join(getattr(p, 'text', '') or '' for p in parts).strip()
                    logger.debug(f"LLM client: extracted text from message.parts ({len(parts)} parts) model={model!r}")

            if finish == 'length':
                logger.warning(
                    f"LLM client: response truncated (finish_reason='length') model={model!r} "
                    f"— increase max_tokens; got {len(text)} chars so far"
                )

            if not text:
                logger.warning(
                    f"LLM client: empty content from model={model!r} "
                    f"finish_reason={finish!r} "
                    f"message={message!r}"
                )

            usage = getattr(response, 'usage', None)
            input_tokens  = int(getattr(usage, 'prompt_tokens',     0) or 0) if usage else 0
            output_tokens = int(getattr(usage, 'completion_tokens', 0) or 0) if usage else 0
            total_tokens  = int(getattr(usage, 'total_tokens',      0) or 0) if usage else (input_tokens + output_tokens)
            logger.debug(
                f"LLM client: model={model!r} finish={finish!r} "
                f"tokens={total_tokens} (in={input_tokens} out={output_tokens}) "
                f"text_len={len(text)}"
            )
            return text, total_tokens, input_tokens, output_tokens

        except _retryable as e:
            # litellm formats its Timeout message with None when the provider doesn't
            # propagate the timeout value — patch the exception args in-place so every
            # caller that logs str(e) sees the real number.
            _fix = f'after {_timeout} seconds'
            try:
                e.args = tuple(str(a).replace('after None seconds', _fix) for a in e.args)
            except Exception:
                pass
            if attempt < DEFAULT_RETRIES:
                logger.warning(
                    f"LLM call timed out/connection error (attempt {attempt}/{DEFAULT_RETRIES}), "
                    f"retrying — model={model!r} timeout={_timeout}s error={e}"
                )
                continue
            logger.warning(
                f"LLM call failed after {DEFAULT_RETRIES} attempts ({_timeout}s timeout) "
                f"model={model!r} error={e}"
            )
            raise

        except litellm.BadRequestError as e:
            # If the provider rejected an unsupported sampling param or reasoning
            # payload, drop it and retry once. We used to only do this when the
            # error message *named* the offending field, but not every provider
            # does that — Google's Gemini 3.x 400 INVALID_ARGUMENT responses
            # carry no 'details' field and never mention 'temperature' or
            # 'thinkingConfig' by name. So instead we unconditionally strip
            # anything we ourselves added on top of the caller's messages
            # (sampling params, Gemini's generationConfig.thinkingConfig) the
            # first time a BadRequestError is seen, then retry once.
            # attempt-=1 keeps this off the timeout-retry budget;
            # _stripped_sampling prevents looping. If there's nothing of ours
            # left to strip, `dropped` stays empty and the original error is
            # raised immediately — this can't mask an unrelated 400 (bad key,
            # bad model name, oversized input, ...) beyond one wasted retry.
            if not _stripped_sampling:
                dropped = [p for p in _sampling_params if kwargs.pop(p, None) is not None]
                extra_body = kwargs.get('extra_body')
                if isinstance(extra_body, dict):
                    gen_cfg = extra_body.get('generationConfig')
                    if isinstance(gen_cfg, dict) and gen_cfg.pop('thinkingConfig', None) is not None:
                        dropped.append('thinkingConfig')
                        if not gen_cfg:
                            extra_body.pop('generationConfig', None)
                        if not extra_body:
                            kwargs.pop('extra_body', None)
                if dropped:
                    _stripped_sampling = True
                    attempt -= 1
                    logger.warning(
                        f"LLM client: model={model!r} rejected request ({e}); "
                        f"stripped {dropped} and retrying once"
                    )
                    continue
            logger.warning(f"LLM call failed: model={model!r} error={e}")
            raise

        except Exception as e:
            logger.warning(f"LLM call failed: model={model!r} error={e}")
            raise
