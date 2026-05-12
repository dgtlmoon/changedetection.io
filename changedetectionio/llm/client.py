"""
Thin wrapper around litellm.completion.
Keeps litellm import isolated so the rest of the codebase doesn't depend on it directly,
and makes the call easy to mock in tests.
"""

import os
from loguru import logger

# Default output token cap for JSON-returning calls (intent eval, preview, setup).
# These return small JSON objects — 400 is enough for a verbose explanation while
# still preventing runaway cost. Change summaries pass their own max_tokens via
# _summary_max_tokens() and are NOT subject to this cap.
_MAX_COMPLETION_TOKENS = 400

DEFAULT_TIMEOUT = int(os.getenv('LLM_TIMEOUT', 60))
DEFAULT_RETRIES = 3


def completion(model: str, messages: list, api_key: str = None,
               api_base: str = None, timeout: int = DEFAULT_TIMEOUT,
               max_tokens: int = None, extra_body: dict = None) -> tuple[str, int, int, int]:
    """
    Call the LLM and return (response_text, total_tokens, input_tokens, output_tokens).
    Retries up to DEFAULT_RETRIES times on timeout or connection errors.
    Token counts are 0 if the provider doesn't return usage data.
    Raises on network/auth errors — callers handle gracefully.
    """
    try:
        import litellm
    except ImportError:
        raise RuntimeError("litellm is not installed. Add it to requirements.txt.")

    _timeout = timeout if timeout is not None else DEFAULT_TIMEOUT

    kwargs = {
        'model': model,
        'messages': messages,
        'timeout': _timeout,
        'temperature': 0,
        'max_tokens': max_tokens if max_tokens is not None else _MAX_COMPLETION_TOKENS,
    }
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base
    if extra_body:
        kwargs['extra_body'] = extra_body

    _retryable = (litellm.Timeout, litellm.APIConnectionError)

    logger.trace("Sending payload to LLM.. ")
    logger.trace(messages)

    for attempt in range(1, DEFAULT_RETRIES + 1):
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

        except Exception as e:
            logger.warning(f"LLM call failed: model={model!r} error={e}")
            raise
