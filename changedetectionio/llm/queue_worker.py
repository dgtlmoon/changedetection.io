import os
import queue
import re
import threading
import time
from loguru import logger

from changedetectionio.llm.tokens import (
    STRUCTURED_OUTPUT_INSTRUCTION,
    parse_llm_response,
    write_llm_data,
)

MAX_RETRIES = 5
RETRY_BACKOFF_BASE_SECONDS = 60  # 1m, 2m, 4m, 8m, 16m

# Token thresholds that control which summarisation strategy is used.
# Small diffs: single-pass summarise.
# Larger diffs: two-pass (enumerate all changes first, then compress).
# Very large diffs: map-reduce (chunk → enumerate per chunk → final synthesis).
TOKEN_SINGLE_PASS_THRESHOLD = 5000   # below this: one call
TOKEN_TWO_PASS_THRESHOLD    = 15000  # below this: enumerate then summarise
TOKEN_CHUNK_SIZE            = 5000   # tokens per map-reduce chunk


# ---------------------------------------------------------------------------
# Proactive token-bucket rate limiter — shared across all workers in process
# ---------------------------------------------------------------------------

class _RateLimitWait(Exception):
    """Raised when the bucket is empty; worker re-queues without incrementing attempts."""
    def __init__(self, wait_seconds):
        self.wait_seconds = wait_seconds
        super().__init__(f"Rate limit: wait {wait_seconds:.1f}s")


class _TokenBucket:
    """Thread-safe continuous token bucket. tpm=0 means unlimited."""

    def __init__(self, tpm):
        self._lock    = threading.Lock()
        self._tpm     = tpm
        self._tokens  = float(tpm)           # start full
        self._last_ts = time.monotonic()

    def try_consume(self, n):
        """Consume n tokens.  Returns (True, 0.0) on success or (False, wait_secs) if dry."""
        if self._tpm == 0:
            return True, 0.0
        with self._lock:
            now     = time.monotonic()
            elapsed = now - self._last_ts
            self._tokens  = min(self._tpm, self._tokens + elapsed * (self._tpm / 60.0))
            self._last_ts = now
            if self._tokens >= n:
                self._tokens -= n
                return True, 0.0
            deficit = n - self._tokens
            return False, deficit / (self._tpm / 60.0)


_rate_buckets      = {}
_rate_buckets_lock = threading.Lock()


def _get_rate_bucket(conn_id, tpm):
    """Return (or lazily create) the shared _TokenBucket for this connection."""
    with _rate_buckets_lock:
        if conn_id not in _rate_buckets:
            _rate_buckets[conn_id] = _TokenBucket(int(tpm or 0))
        return _rate_buckets[conn_id]


def _parse_retry_after(exc):
    """Extract a retry-after delay (seconds) from a litellm RateLimitError."""
    if hasattr(exc, 'retry_after') and exc.retry_after:
        try:
            return float(exc.retry_after)
        except (TypeError, ValueError):
            pass
    m = re.search(r'(?:try again in|retry after)\s*([\d.]+)\s*s', str(exc), re.IGNORECASE)
    return float(m.group(1)) + 1.0 if m else 60.0


def _read_snapshot(watch, snapshot_fname):
    """Read a snapshot file from disk, handling plain text and brotli compression."""
    path = os.path.join(watch.data_dir, snapshot_fname)
    if snapshot_fname.endswith('.br'):
        import brotli
        with open(path, 'rb') as f:
            return brotli.decompress(f.read()).decode('utf-8', errors='replace')
    else:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            return f.read()


def _call_llm(model, messages, api_key=None, api_base=None, max_tokens=600, conn_id=None, tpm=0):
    """
    Thin wrapper around litellm.completion.
    Isolated as a named function so tests can mock.patch it without importing litellm.

    Determinism settings
    --------------------
    temperature=0   — greedy decoding; same input produces the same output consistently.
    seed=0          — passed through to providers that support it (OpenAI, some others)
                      for near-bit-identical reproducibility across calls.

    Deliberately NOT set
    --------------------
    top_p           — redundant at temperature=0 and can interact badly with some providers.
    frequency_penalty / presence_penalty — would penalise the model for repeating specific
                      values (e.g. "$10 → $10") which is exactly wrong for change detection.

    max_tokens      — caller sets this based on the pass type:
                      enumerate pass needs more room than the final summary pass.

    conn_id / tpm   — optional rate limiting; when both are set, a proactive token-bucket
                      check is performed before calling the API.  Raises _RateLimitWait if
                      the bucket is empty so the worker can re-queue without retrying.

    Returns the response text string.
    """
    import litellm

    # Proactive rate check (skipped when tpm=0 or conn_id is None)
    if conn_id and tpm:
        prompt_tokens = litellm.token_counter(model=model, messages=messages)
        total_est     = prompt_tokens + max_tokens
        bucket        = _get_rate_bucket(conn_id, tpm)
        ok, wait      = bucket.try_consume(total_est)
        if not ok:
            raise _RateLimitWait(wait)

    kwargs = dict(
        model=model,
        messages=messages,
        temperature=0,
        seed=0,
        max_tokens=max_tokens,
    )
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base

    response = litellm.completion(**kwargs)
    return response.choices[0].message.content.strip()


def _write_summary(watch_dir, snapshot_id, text):
    """Write the LLM summary to {snapshot_id}-llm.txt alongside the snapshot."""
    dest = os.path.join(watch_dir, f"{snapshot_id}-llm.txt")
    tmp = dest + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dest)
    return dest


def _resolve_llm_connection(watch, datastore):
    """Return (model, api_key, api_base, conn_id, tpm) for the given watch.

    Resolution order:
    1. Watch-level connection_id pointing to a named entry in plugin settings.
    2. The default entry in plugin settings (is_default=True).
    3. Legacy flat fields on the watch or in global settings — backward compat.
    4. Hard-coded fallback: gpt-4o-mini with no key / base.
    """
    from changedetectionio.llm.plugin import get_llm_settings
    from changedetectionio.llm.settings_form import sanitised_conn_id

    llm_settings = get_llm_settings(datastore)
    connections  = llm_settings.get('llm_connection') or []

    # 1. Watch-level override by explicit connection_id
    watch_conn_id = watch.get('llm_connection_id')
    if watch_conn_id:
        for c in connections:
            if c.get('connection_id') == watch_conn_id:
                cid = sanitised_conn_id(c.get('connection_id', ''))
                return (c.get('model', 'gpt-4o-mini'), c.get('api_key', ''), c.get('api_base', ''),
                        cid, int(c.get('tokens_per_minute', 0) or 0))

    # 2. Global default connection
    for c in connections:
        if c.get('is_default'):
            cid = sanitised_conn_id(c.get('connection_id', ''))
            return (c.get('model', 'gpt-4o-mini'), c.get('api_key', ''), c.get('api_base', ''),
                    cid, int(c.get('tokens_per_minute', 0) or 0))

    # 3. Legacy flat fields (backward compat)
    app_settings = datastore.data['settings']['application']
    model    = watch.get('llm_model')    or app_settings.get('llm_model',    'gpt-4o-mini')
    api_key  = watch.get('llm_api_key')  or app_settings.get('llm_api_key',  '')
    api_base = watch.get('llm_api_base') or app_settings.get('llm_api_base', '')
    return model, api_key, api_base, 'legacy', 0


SYSTEM_PROMPT = (
    'You are a change detection assistant. '
    'Be precise and factual. Never speculate. '
    'Always use exact numbers, values, and quoted text when present in the diff. '
    'If nothing meaningful changed, say so explicitly.'
)


def _chunk_lines(lines, model, chunk_token_size):
    """Split lines into chunks that each fit within chunk_token_size tokens."""
    import litellm
    chunks, current, current_tokens = [], [], 0
    for line in lines:
        line_tokens = litellm.token_counter(model=model, text=line)
        if current and current_tokens + line_tokens > chunk_token_size:
            chunks.append('\n'.join(current))
            current, current_tokens = [], 0
        current.append(line)
        current_tokens += line_tokens
    if current:
        chunks.append('\n'.join(current))
    return chunks


def _enumerate_changes(diff_text, url, model, llm_kwargs):
    """
    Pass 1 — ask the model to list every distinct change exhaustively, one per line.
    Returns a plain-text list string.
    This avoids compression decisions: the model just lists, it does not prioritise.
    """
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {
            'role': 'user',
            'content': (
                f"URL: {url}\n"
                f"Diff:\n{diff_text}\n\n"
                "List every distinct change you see, one item per line. "
                "Be exhaustive — do not filter or prioritise. "
                "Use exact values from the diff (prices, dates, counts, quoted text)."
            ),
        },
    ]
    # Enumerate pass needs more output room than the final summary
    return _call_llm(model=model, messages=messages, max_tokens=1200, **llm_kwargs)


def _summarise_enumeration(enumerated, url, model, llm_kwargs, summary_instruction=None):
    """
    Pass 2 — compress the exhaustive enumeration into the final output.
    Operates on a small, structured input so nothing is lost that wasn't already listed.
    summary_instruction overrides the default STRUCTURED_OUTPUT_INSTRUCTION when set.
    """
    instruction = summary_instruction or (
        "Now produce the final structured output for all of these changes.\n\n"
        + STRUCTURED_OUTPUT_INSTRUCTION
    )
    messages = [
        {'role': 'system', 'content': SYSTEM_PROMPT},
        {
            'role': 'user',
            'content': (
                f"URL: {url}\n"
                f"All changes detected:\n{enumerated}\n\n"
                + instruction
            ),
        },
    ]
    return _call_llm(model=model, messages=messages, max_tokens=500, **llm_kwargs)


def process_llm_summary(item, datastore):
    """
    Generate an LLM summary for a detected change and write {snapshot_id}-llm.txt.

    item keys:
        uuid        - watch UUID
        snapshot_id - the newer snapshot ID (md5 hex), maps to {snapshot_id}.txt[.br]
        attempts    - retry counter

    Summarisation strategy (chosen by diff token count):
        Small  (< SINGLE_PASS_TOKEN_LIMIT):  one call — enumerate + summarise together.
        Medium (< TWO_PASS_TOKEN_LIMIT):     two calls — enumerate all changes, then compress.
        Large  (≥ TWO_PASS_TOKEN_LIMIT):     map-reduce — chunk → enumerate per chunk →
                                             synthesise chunk enumerations → final summary.

    The two-pass / map-reduce approach prevents lossiness: temperature=0 causes the model
    to greedily commit to the most prominent change and drop the rest in a single pass.
    Enumerating first forces comprehensive coverage before any compression happens.

    Split into _call_llm / _write_summary so each step is independently patchable in tests.
    """
    import difflib
    import litellm

    uuid        = item['uuid']
    snapshot_id = item['snapshot_id']

    watch = datastore.data['watching'].get(uuid)
    if not watch:
        raise ValueError(f"Watch {uuid} not found")

    # Find this snapshot and the one before it in history
    history      = watch.history
    history_keys = list(history.keys())

    try:
        idx = next(
            i for i, k in enumerate(history_keys)
            if os.path.basename(history[k]).split('.')[0] == snapshot_id
        )
    except StopIteration:
        raise ValueError(f"snapshot_id {snapshot_id} not found in history for watch {uuid}")

    if idx == 0:
        raise ValueError(f"snapshot_id {snapshot_id} is the first history entry — no prior to diff against")

    before_text  = _read_snapshot(watch, history[history_keys[idx - 1]])
    current_text = _read_snapshot(watch, history[history_keys[idx]])

    diff_lines = list(difflib.unified_diff(
        before_text.splitlines(),
        current_text.splitlines(),
        lineterm='',
        n=2,
    ))
    diff_text = '\n'.join(diff_lines)

    if not diff_text.strip():
        logger.debug(f"LLM: no diff content for {uuid}/{snapshot_id}, skipping")
        return

    # Resolve model / credentials via connections table (with legacy flat-field fallback)
    model, api_key, api_base, conn_id, tpm = _resolve_llm_connection(watch, datastore)
    url = watch.get('url', '')

    llm_kwargs = {}
    if api_key:
        llm_kwargs['api_key'] = api_key
    if api_base:
        llm_kwargs['api_base'] = api_base
    if conn_id:
        llm_kwargs['conn_id'] = conn_id
    if tpm:
        llm_kwargs['tpm'] = tpm

    # Use custom prompt if configured, otherwise fall back to the built-in default
    from changedetectionio.llm.plugin import get_llm_settings
    llm_settings  = get_llm_settings(datastore)
    custom_prompt = (llm_settings.get('llm_summary_prompt') or '').strip()
    summary_instruction = custom_prompt if custom_prompt else (
        "Analyse all changes in this diff.\n\n" + STRUCTURED_OUTPUT_INSTRUCTION
    )

    diff_tokens = litellm.token_counter(model=model, text=diff_text)
    logger.debug(f"LLM: diff is {diff_tokens} tokens for {uuid}/{snapshot_id}")

    if diff_tokens < TOKEN_SINGLE_PASS_THRESHOLD:
        # Small diff — single call, model can see everything at once
        messages = [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {
                'role': 'user',
                'content': (
                    f"URL: {url}\n"
                    f"Diff:\n{diff_text}\n\n"
                    + summary_instruction
                ),
            },
        ]
        raw = _call_llm(model=model, messages=messages, max_tokens=500, **llm_kwargs)
        strategy = 'single'

    elif diff_tokens < TOKEN_TWO_PASS_THRESHOLD:
        # Medium diff — two-pass: enumerate exhaustively, then compress
        enumerated = _enumerate_changes(diff_text, url, model, llm_kwargs)
        raw        = _summarise_enumeration(enumerated, url, model, llm_kwargs, summary_instruction)
        strategy   = 'two-pass'

    else:
        # Large diff — map-reduce: chunk → enumerate per chunk → synthesise
        chunks = _chunk_lines(diff_lines, model, TOKEN_CHUNK_SIZE)
        logger.debug(f"LLM: map-reduce over {len(chunks)} chunks for {uuid}/{snapshot_id}")

        chunk_enumerations = []
        for i, chunk in enumerate(chunks):
            logger.debug(f"LLM: enumerating chunk {i+1}/{len(chunks)}")
            chunk_enumerations.append(
                _enumerate_changes(chunk, url, model, llm_kwargs)
            )

        combined = '\n'.join(chunk_enumerations)
        raw      = _summarise_enumeration(combined, url, model, llm_kwargs, summary_instruction)
        strategy = 'map-reduce'

    llm_data = parse_llm_response(raw)
    write_llm_data(watch.data_dir, snapshot_id, llm_data)
    logger.info(f"LLM tokens written for {uuid}/{snapshot_id} (strategy: {strategy}, tokens: {diff_tokens})")


def llm_summary_runner(worker_id, app, datastore, llm_q):
    """
    Sync LLM summary worker — mirrors the notification_runner pattern.

    One worker is the right default (LLM API rate limits constrain throughput
    more than parallelism helps). Increase via LLM_WORKERS env var if using
    a local Ollama endpoint with no rate limits.

    Failed items are re-queued with exponential backoff (see MAX_RETRIES /
    RETRY_BACKOFF_BASE_SECONDS). After MAX_RETRIES the item is dropped and
    the failure is recorded on the watch.
    """
    with app.app_context():
        while not app.config.exit.is_set():
            try:
                item = llm_q.get(block=False)
            except queue.Empty:
                app.config.exit.wait(1)
                continue

            # Honour retry delay — if the item isn't due yet, put it back
            # and sleep briefly rather than spinning.
            next_retry_at = item.get('next_retry_at', 0)
            if next_retry_at > time.time():
                llm_q.put(item)
                app.config.exit.wait(min(next_retry_at - time.time(), 5))
                continue

            uuid        = item.get('uuid')
            snapshot_id = item.get('snapshot_id')
            attempts    = item.get('attempts', 0)

            logger.debug(f"LLM worker {worker_id} processing uuid={uuid} snapshot={snapshot_id} attempt={attempts}")

            try:
                process_llm_summary(item, datastore)
                logger.info(f"LLM worker {worker_id} completed summary for uuid={uuid} snapshot={snapshot_id}")

            except NotImplementedError:
                # Silently drop until the processor is implemented
                logger.debug(f"LLM worker {worker_id} skipping — processor not yet implemented")

            except _RateLimitWait as rw:
                # Proactive bucket empty — re-queue without counting as a failure
                item['next_retry_at'] = time.time() + rw.wait_seconds
                llm_q.put(item)
                logger.info(
                    f"LLM worker {worker_id} rate-limited (proactive) for {rw.wait_seconds:.1f}s "
                    f"uuid={uuid}"
                )

            except Exception as e:
                # Reactive: check if the API itself returned a rate-limit error
                try:
                    import litellm as _litellm
                    if isinstance(e, _litellm.RateLimitError):
                        wait = _parse_retry_after(e)
                        item['next_retry_at'] = time.time() + wait
                        llm_q.put(item)
                        logger.warning(
                            f"LLM worker {worker_id} API rate limit for uuid={uuid}, "
                            f"retry in {wait:.1f}s"
                        )
                        continue
                except ImportError:
                    pass

                logger.error(f"LLM worker {worker_id} error for uuid={uuid} snapshot={snapshot_id}: {e}")

                if attempts < MAX_RETRIES:
                    backoff = RETRY_BACKOFF_BASE_SECONDS * (2 ** attempts)
                    item['attempts']      = attempts + 1
                    item['next_retry_at'] = time.time() + backoff
                    llm_q.put(item)
                    logger.info(
                        f"LLM worker {worker_id} re-queued uuid={uuid} "
                        f"attempt={item['attempts']}/{MAX_RETRIES} retry_in={backoff}s"
                    )
                else:
                    logger.error(
                        f"LLM worker {worker_id} gave up on uuid={uuid} snapshot={snapshot_id} "
                        f"after {MAX_RETRIES} attempts"
                    )
                    if uuid and uuid in datastore.data['watching']:
                        datastore.update_watch(
                            uuid=uuid,
                            update_obj={'last_error': f"LLM summary failed after {MAX_RETRIES} attempts: {e}"}
                        )
