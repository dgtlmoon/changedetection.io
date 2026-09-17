"""
Parse and validate LLM JSON responses.
Pure functions — no side effects, fully testable.

LLMs occasionally return JSON wrapped in markdown fences or with trailing
text. This module handles those cases gracefully.
"""

import json
import re

from changedetectionio.strtobool import strtobool

# Positional selectors are fragile — reject them even if the LLM generates them
_POSITIONAL_SELECTOR_RE = re.compile(
    r'nth-child|nth-of-type|:eq\(|\[\d+\]|\/\/\*\[\d', re.IGNORECASE
)

# Reasoning models (DeepSeek-R1, Qwen reasoning, etc.) wrap their scratchpad in <think> tags.
# Three shapes have to be handled, because the scratchpad routinely contains JSON of its own
# ("initially I thought {"important": false}, but..."), so leaving any of it in place lets
# _extract_json lock onto a discarded intermediate answer instead of the real one.
_THINK_BLOCK_RE = re.compile(r'<think(?:ing)?>.*?</think(?:ing)?>', re.DOTALL | re.IGNORECASE)
_THINK_TAIL_RE = re.compile(r'^.*</think(?:ing)?>', re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r'<think(?:ing)?>', re.IGNORECASE)


def _to_bool(value, default: bool = False) -> bool:
    """Safely coerce boolean values from LLM responses.

    Handles native booleans, truthy/falsy integers (1/0), and string booleans
    ("true", "false", "yes", "no", "1", "0") using strtobool.
    Avoids Python's bool("false") -> True bug on stringified JSON booleans.
    """
    if value is None:
        return default
    try:
        return strtobool(value)
    except (ValueError, AttributeError):
        return default


def _extract_json(raw: str) -> str:
    """Strip reasoning blocks, markdown fences, and extract the first JSON object.

    Raises:
        ValueError: the response opens a reasoning block it never closes, i.e. it was cut
            off mid-thought (usually by max_tokens) and contains no answer at all. Callers
            in evaluator.py catch this and fall back safely - for diff evaluation that
            means passing the change through as important rather than silently dropping it.
    """
    raw = raw.strip()
    # Well-formed scratchpads.
    raw = _THINK_BLOCK_RE.sub('', raw).strip()
    # Some providers/chat templates emit the opening tag themselves and only the closer comes
    # back over the wire, so anything up to the last closer is still scratchpad.
    raw = _THINK_TAIL_RE.sub('', raw).strip()
    # An opener with no closer means the response was truncated part-way through reasoning.
    # There is no answer to find; the only JSON present would be a discarded intermediate one.
    if _THINK_OPEN_RE.search(raw):
        raise ValueError('LLM response contains an unterminated reasoning block (truncated?)')
    # Remove ```json ... ``` or ``` ... ``` fences
    raw = re.sub(r'^```(?:json)?\s*', '', raw, flags=re.MULTILINE)
    raw = re.sub(r'\s*```$', '', raw, flags=re.MULTILINE)
    # Find the first { ... } block
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    return match.group(0) if match else raw


def parse_eval_response(raw: str) -> dict:
    """
    Parse a diff evaluation response.
    Returns {'important': bool, 'summary': str}.
    Falls back to important=False on any parse error.
    """
    try:
        data = json.loads(_extract_json(raw))
        return {
            'important': _to_bool(data.get('important'), default=False),
            'summary': str(data.get('summary', '')).strip(),
        }
    except (json.JSONDecodeError, AttributeError):
        return {'important': False, 'summary': ''}


def parse_preview_response(raw: str) -> dict:
    """
    Parse a live-preview extraction response.
    Returns {'found': bool, 'answer': str}.
    Falls back to found=False on any parse error.
    """
    try:
        data = json.loads(_extract_json(raw))
        return {
            'found': _to_bool(data.get('found'), default=False),
            'answer': str(data.get('answer', '')).strip(),
        }
    except (json.JSONDecodeError, AttributeError):
        return {'found': False, 'answer': ''}


def parse_setup_response(raw: str) -> dict:
    """
    Parse a setup/pre-filter decision response.
    Returns {'needs_prefilter': bool, 'selector': str|None, 'reason': str}.
    Rejects positional selectors even if the LLM generates them.
    """
    try:
        data = json.loads(_extract_json(raw))
        needs = _to_bool(data.get('needs_prefilter'), default=False)
        selector = data.get('selector') or None

        # Sanitise: reject positional selectors
        if selector and _POSITIONAL_SELECTOR_RE.search(selector):
            selector = None
            needs = False

        return {
            'needs_prefilter': needs,
            'selector': selector if needs else None,
            'reason': str(data.get('reason', '')).strip(),
        }
    except (json.JSONDecodeError, AttributeError):
        return {'needs_prefilter': False, 'selector': None, 'reason': ''}
