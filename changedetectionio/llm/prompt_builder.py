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


def build_preview_prompt(intent: str, content: str, url: str = '', title: str = '') -> str:
    """
    Build the user message for a live-preview extraction call.
    Unlike build_eval_prompt (which analyses a diff), this asks the LLM to
    extract relevant information from the *current* page content — giving the
    user a direct answer to their intent so they can verify it makes sense
    before saving.
    """
    parts = []
    if url:
        parts.append(f"URL: {url}")
    if title:
        parts.append(f"Page title: {title}")
    parts.append(f"Intent / question: {intent}")
    parts.append(f"\nPage content:\n{content[:6_000]}")
    return '\n'.join(parts)


def build_preview_system_prompt() -> str:
    return (
        "You are a web page content analyzer for a website monitoring tool.\n"
        "Given the user's intent or question and the current page content, "
        "extract and directly answer what the intent is looking for.\n\n"
        "Respond with ONLY a JSON object — no markdown, no explanation outside it:\n"
        '{"found": true/false, "answer": "concise direct answer or extraction"}\n\n'
        "Rules:\n"
        "- found=true when the page contains something relevant to the intent\n"
        "- answer must directly address the intent (e.g. for 'how many articles?' → '30 articles listed')\n"
        "- answer must be in the same language as the intent\n"
        "- Keep answer brief — one sentence maximum"
    )


def build_change_summary_prompt(diff: str, custom_prompt: str,
                                current_snapshot: str = '', url: str = '', title: str = '') -> str:
    """
    Build the user message for an AI Change Summary call.
    The user supplies their own instructions (custom_prompt); this wraps them
    with the diff and optional page context.
    """
    parts = []
    if url:
        parts.append(f"URL: {url}")
    if title:
        parts.append(f"Page title: {title}")
    parts.append(f"Instructions: {custom_prompt}")
    if current_snapshot:
        excerpt = trim_to_relevant(current_snapshot, custom_prompt, max_chars=2_000)
        if excerpt:
            parts.append(f"\nCurrent page (excerpt):\n{excerpt}")
    parts.append(f"\nWhat changed (diff):\n{diff}")
    return '\n'.join(parts)


def build_change_summary_system_prompt() -> str:
    return (
        "You summarise website changes for a monitoring notification.\n"
        "Given a diff of what changed and the user's formatting instructions, "
        "produce a concise plain-language description of the change.\n"
        "Follow the user's instructions exactly for format, language, and length.\n"
        "Respond with ONLY the summary text — no JSON, no markdown code fences, "
        "no preamble. Just the description."
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
