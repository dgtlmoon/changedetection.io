"""
LLM notification token definitions and file I/O helpers.

All LLM data for a snapshot is stored under a dedicated subdirectory:
    {data_dir}/llm/{snapshot_id}-llm.json

A plain-text {snapshot_id}-llm.txt is also written containing just the
summary field, for backward compatibility with any code that already reads it.

Token catalogue
---------------
llm_summary     1-3 sentence description of all changes, exact values.
llm_headline    5-8 word punchy title — ideal for the notification subject line.
llm_importance  Numeric 1-10 significance score; enables routing rules like
                "only escalate if llm_importance >= 8".
llm_sentiment   Machine-readable: "positive", "negative", or "neutral".
                Useful for trend tracking and coloured alert styling.
llm_one_liner   Shortest useful summary — one sentence for SMS, Pushover,
                and other character-limited channels.
"""

import os
import json
from loguru import logger

# ── Constants ──────────────────────────────────────────────────────────────

LLM_TOKEN_NAMES = (
    'llm_summary',
    'llm_headline',
    'llm_importance',
    'llm_sentiment',
    'llm_one_liner',
)

# How long the notification runner waits for LLM data before giving up.
LLM_NOTIFICATION_RETRY_DELAY_SECONDS = int(os.getenv('LLM_NOTIFICATION_RETRY_DELAY', '10'))
LLM_NOTIFICATION_MAX_WAIT_ATTEMPTS   = int(os.getenv('LLM_NOTIFICATION_MAX_WAIT',    '18'))  # 18 × 10s = 3 min

# JSON prompt fragment — embedded in the final summarisation call.
STRUCTURED_OUTPUT_INSTRUCTION = (
    'Return ONLY a valid JSON object — no markdown fences, no extra text — using exactly these keys:\n'
    '{"summary":"1-3 sentences covering ALL changes; use exact values from the diff.","headline":"5-8 word punchy title for this specific change","importance":7,"sentiment":"positive","one_liner":"One sentence for SMS/push character limits."}\n'
    'importance: 1=trivial whitespace, 5=moderate content change, 10=critical price/availability change.\n'
    'sentiment: "positive" (desirable for the user), "negative" (undesirable), or "neutral" (informational only).'
)


# ── File I/O ───────────────────────────────────────────────────────────────

def llm_subdir(data_dir: str) -> str:
    """Return the llm/ subdirectory path (does not create it)."""
    return os.path.join(data_dir, 'llm')


def llm_json_path(data_dir: str, snapshot_id: str) -> str:
    return os.path.join(llm_subdir(data_dir), f"{snapshot_id}-llm.json")


def llm_txt_path(data_dir: str, snapshot_id: str) -> str:
    return os.path.join(llm_subdir(data_dir), f"{snapshot_id}-llm.txt")


def is_llm_data_ready(data_dir: str, snapshot_id: str) -> bool:
    """Return True if LLM data has been written for this snapshot."""
    return os.path.exists(llm_json_path(data_dir, snapshot_id)) or \
           os.path.exists(llm_txt_path(data_dir, snapshot_id))


def read_llm_tokens(data_dir: str, snapshot_id: str) -> dict:
    """
    Read LLM token data for a snapshot.

    Tries JSON first (new format), falls back to plain .txt (old format).
    Returns an empty dict if no data is available yet.
    """
    json_file = llm_json_path(data_dir, snapshot_id)
    if os.path.exists(json_file):
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                return _normalise(data)
        except Exception as exc:
            logger.warning(f"LLM tokens: failed to read {json_file}: {exc}")

    txt_file = llm_txt_path(data_dir, snapshot_id)
    if os.path.exists(txt_file):
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                summary = f.read().strip()
            return _normalise({'summary': summary, 'one_liner': summary[:200]})
        except Exception as exc:
            logger.warning(f"LLM tokens: failed to read {txt_file}: {exc}")

    return {}


def write_llm_data(data_dir: str, snapshot_id: str, data: dict) -> str:
    """
    Atomically write LLM data to the llm/ subdirectory.

    Writes:
      llm/{snapshot_id}-llm.json  — full structured data (all tokens)
      llm/{snapshot_id}-llm.txt   — plain summary text (backward compat)

    Returns the path of the JSON file.
    """
    normalised = _normalise(data)

    subdir = llm_subdir(data_dir)
    os.makedirs(subdir, exist_ok=True)

    json_file = llm_json_path(data_dir, snapshot_id)
    _atomic_write_text(json_file, json.dumps(normalised, ensure_ascii=False))

    txt_file = llm_txt_path(data_dir, snapshot_id)
    _atomic_write_text(txt_file, normalised.get('summary', ''))

    return json_file


def parse_llm_response(response: str) -> dict:
    """
    Parse a structured JSON response from the LLM.

    Tries strict JSON parse, then extracts from markdown code fences,
    then a bare object search.  Falls back to treating the whole response
    as the 'summary' field if nothing parses.
    """
    import re
    text = response.strip()

    # 1. Direct JSON parse
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return _normalise(obj)
    except (json.JSONDecodeError, ValueError):
        pass

    # 2. Markdown code fence: ```json { ... } ```
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return _normalise(obj)
        except (json.JSONDecodeError, ValueError):
            pass

    # 3. Bare JSON object anywhere in the response
    m = re.search(r'\{[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return _normalise(obj)
        except (json.JSONDecodeError, ValueError):
            pass

    # 4. Fallback — treat entire response as summary
    logger.debug("LLM response was not valid JSON — using raw text as summary")
    return _normalise({'summary': text, 'one_liner': text[:200] if len(text) > 200 else text})


# ── Internal helpers ───────────────────────────────────────────────────────

def _normalise(data: dict) -> dict:
    """Return a clean token dict with all expected keys present."""
    importance = data.get('importance')
    if importance is not None:
        try:
            importance = max(1, min(10, int(float(importance))))
        except (TypeError, ValueError):
            importance = None

    sentiment = str(data.get('sentiment', '')).lower().strip()
    if sentiment not in ('positive', 'negative', 'neutral'):
        sentiment = ''

    return {
        'summary':    str(data.get('summary',   '') or '').strip(),
        'headline':   str(data.get('headline',  '') or '').strip(),
        'importance': importance,
        'sentiment':  sentiment,
        'one_liner':  str(data.get('one_liner', '') or '').strip(),
    }


def _atomic_write_text(path: str, text: str) -> None:
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
