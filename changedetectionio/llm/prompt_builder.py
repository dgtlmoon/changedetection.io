"""
Prompt construction for LLM evaluation calls.
Pure functions — no side effects, fully testable.
"""

from .bm25_trim import trim_to_relevant

SNAPSHOT_CONTEXT_CHARS = 3_000   # current page state excerpt sent alongside the diff


def build_eval_prompt(intent: str, diff: str, current_snapshot: str = '',
                      url: str = '', title: str = '') -> str:
    """
    Build the user message for a diff evaluation call.
    The system prompt is kept separate (see build_eval_system_prompt).
    """
    parts = []

    if url:
        parts.append(f"URL: {url}")
    if title:
        parts.append(f"Page title: {title}")

    parts.append(f"Intent: {intent}")

    if current_snapshot:
        excerpt = trim_to_relevant(current_snapshot, intent, max_chars=SNAPSHOT_CONTEXT_CHARS)
        if excerpt:
            parts.append(f"\nCurrent page state (relevant excerpt):\n{excerpt}")

    parts.append(f"\nWhat changed (diff):\n{diff}")

    return '\n'.join(parts)


def build_eval_system_prompt() -> str:
    return (
        "You evaluate website changes for a monitoring tool.\n"
        "Given an intent and a diff (added/removed lines), decide if the change matches the intent.\n\n"
        "Respond with ONLY a JSON object — no markdown, no explanation outside it:\n"
        '{"important": true/false, "summary": "one sentence describing the relevant change, or why it doesn\'t match"}\n\n'
        "Rules:\n"
        "- important=true only when the diff clearly matches the intent\n"
        "- Empty, trivial, or cosmetic diffs (dates, counters, whitespace) → important=false\n"
        "- Use OR logic when intent lists multiple triggers\n"
        "- Summary must be in the same language as the intent\n"
        "- If important=false, summary briefly explains why it doesn't match"
    )


def build_setup_prompt(intent: str, snapshot_text: str, url: str = '') -> str:
    """
    Build the prompt for the one-time setup call that decides whether
    a CSS pre-filter would improve evaluation precision.
    """
    excerpt = trim_to_relevant(snapshot_text, intent, max_chars=4_000)

    parts = []
    if url:
        parts.append(f"URL: {url}")
    parts.append(f"Intent: {intent}")
    parts.append(f"\nPage content excerpt:\n{excerpt}")

    return '\n'.join(parts)


def build_setup_system_prompt() -> str:
    return (
        "You help configure a website change monitor.\n"
        "Given a monitoring intent and a sample of the page content, decide if a CSS pre-filter "
        "would improve evaluation precision by scoping the content to a specific structural section.\n\n"
        "Respond with ONLY a JSON object:\n"
        '{"needs_prefilter": true/false, "selector": "CSS selector or null", "reason": "one sentence"}\n\n'
        "Rules:\n"
        "- Only recommend a pre-filter when the intent references a specific structural section "
        "(e.g. 'footer', 'sidebar', 'nav', 'header', 'main', 'article') OR the page clearly "
        "has high-noise sections unrelated to the intent\n"
        "- Use ONLY semantic element selectors: footer, nav, header, main, article, aside, "
        "or attribute-based like [id*='price'], [class*='sidebar'] — NEVER positional selectors "
        "like div:nth-child(3) or //*[2]\n"
        "- Default to needs_prefilter=false — most intents don't need one\n"
        "- selector must be null when needs_prefilter=false"
    )
