"""
Thin wrapper around litellm.completion.
Keeps litellm import isolated so the rest of the codebase doesn't depend on it directly,
and makes the call easy to mock in tests.
"""

from loguru import logger

# Output token cap for all LLM calls — our JSON response is always <50 tokens,
# so 200 is a generous hard cap that prevents runaway per-call cost.
_MAX_COMPLETION_TOKENS = 200


def completion(model: str, messages: list, api_key: str = None,
               api_base: str = None, timeout: int = 30,
               max_tokens: int = None) -> tuple[str, int, int, int]:
    """
    Call the LLM and return (response_text, total_tokens, input_tokens, output_tokens).
    Token counts are 0 if the provider doesn't return usage data.
    Raises on network/auth errors — callers handle gracefully.
    """
    try:
        import litellm
    except ImportError:
        raise RuntimeError("litellm is not installed. Add it to requirements.txt.")

    kwargs = {
        'model': model,
        'messages': messages,
        'timeout': timeout,
        'temperature': 0,
        'max_tokens': max_tokens if max_tokens is not None else _MAX_COMPLETION_TOKENS,
    }
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base

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
    except Exception as e:
        logger.warning(f"LLM call failed: model={model!r} error={e}")
        raise
