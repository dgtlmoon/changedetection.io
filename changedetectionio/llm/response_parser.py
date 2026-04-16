"""
Parse and validate LLM JSON responses.
Pure functions — no side effects, fully testable.

LLMs occasionally return JSON wrapped in markdown fences or with trailing
text. This module handles those cases gracefully.
"""

import json
import re

# Positional selectors are fragile — reject them even if the LLM generates them
_POSITIONAL_SELECTOR_RE = re.compile(
    r'nth-child|nth-of-type|:eq\(|\[\d+\]|\/\/\*\[\d',
    re.IGNORECASE
)


def _extract_json(raw: str) -> str:
    """Strip markdown fences and extract the first JSON object."""
    raw = raw.strip()
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
            'important': bool(data.get('important', False)),
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
            'found': bool(data.get('found', False)),
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
        needs = bool(data.get('needs_prefilter', False))
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
