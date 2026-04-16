"""
BM25-based relevance trimming for large snapshot text.

When a snapshot is large and no CSS pre-filter has narrowed it down,
we use BM25 to select the lines most relevant to the user's intent
before sending to the LLM. This keeps the context focused without
an arbitrary char truncation.

Pure functions — no side effects, fully testable.
"""

MAX_CONTEXT_CHARS = 15_000


def trim_to_relevant(text: str, query: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    """
    Return the lines from `text` most relevant to `query` up to `max_chars`.
    If text fits within budget, return it unchanged.
    Falls back to head-truncation if rank_bm25 is unavailable.
    """
    if not text or not query:
        return text or ''

    if len(text) <= max_chars:
        return text

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return text[:max_chars]

    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        # rank-bm25 not installed — fall back to simple head truncation
        return text[:max_chars]

    tokenized = [line.lower().split() for line in lines]
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(query.lower().split())

    ranked = sorted(zip(scores, lines), reverse=True)

    result, total = [], 0
    for _score, line in ranked:
        if total + len(line) + 1 > max_chars:
            break
        result.append(line)
        total += len(line) + 1

    # Re-order selected lines to preserve original document order
    selected = set(result)
    ordered = [l for l in lines if l in selected]
    return '\n'.join(ordered)
