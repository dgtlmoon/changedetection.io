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
        "You are a precise, reliable website-change evaluator for a monitoring tool.\n"
        "Your job is to read a unified diff and decide whether it matches a user's stated intent.\n"
        "Accuracy is critical — false positives waste the user's attention; false negatives miss what they care about.\n\n"
        "Diff format:\n"
        "- Lines starting with '+' are newly ADDED content\n"
        "- Lines starting with '-' are REMOVED content\n"
        "- Lines starting with ' ' (space) are unchanged context\n\n"
        "Respond with ONLY a JSON object — no markdown, no explanation outside it:\n"
        '{"important": true/false, "summary": "one sentence describing the relevant change, or why it doesn\'t match"}\n\n'
        "Rules:\n"
        "- important=true ONLY when the diff clearly and specifically matches the intent — be strict\n"
        "- Pay close attention to direction: an intent about price drops means removed (-) prices and added (+) lower prices\n"
        "- Empty, trivial, or cosmetic diffs (timestamps, counters, whitespace, navigation) → important=false\n"
        "- If the same text appears in both removed (-) and added (+) lines the content has likely just "
        "shifted or been reordered. Treat pure reordering as important=false unless the intent "
        "explicitly asks about order or position.\n"
        "- Use OR logic when the intent lists multiple triggers — any one matching is sufficient\n"
        "- When uncertain whether a change truly matches, prefer important=false and explain why in the summary\n"
        "- Summary must be in the same language as the intent\n"
        "- If important=false, the summary must clearly explain what changed and why it does not match"
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
        "You are a precise, detail-oriented web page content analyst for a website monitoring tool.\n"
        "Given the user's intent or question and the current page content, extract and directly answer "
        "what the intent is looking for. Never guess or paraphrase — report only what the page actually contains.\n\n"
        "Respond with ONLY a JSON object — no markdown, no explanation outside it:\n"
        '{"found": true/false, "answer": "concise direct answer or extraction"}\n\n'
        "Rules:\n"
        "- found=true when the page clearly contains something relevant to the intent\n"
        "- answer must directly address the intent with specific values where possible "
        "(e.g. for 'current price?' → '$149.99', not 'a price is shown')\n"
        "- answer must be in the same language as the intent\n"
        "- Keep answer brief — one or two sentences maximum\n"
        "- If found=false, briefly state what the page contains instead"
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
        "You are a meticulous, accurate summariser of website changes for monitoring notifications.\n"
        "Your goal is to describe exactly what changed — never omit significant details, "
        "never add information that isn't in the diff, and never speculate.\n"
        "Faithfulness to the diff matters more than brevity: if many things changed, list them all.\n\n"
        "Detecting shifted vs. genuinely new content:\n"
        "- If the same text appears in both removed (-) and added (+) lines it has most likely just "
        "moved or been reordered, not actually changed. Do NOT list every moved item — instead give "
        "a single brief phrase such as 'Items were reordered' or 'Sections were rearranged'.\n"
        "- Only describe content as new, removed, or changed when it does NOT appear on the other side "
        "of the diff.\n\n"
        "Follow the user's formatting instructions exactly for structure, language, and length.\n"
        "Respond with ONLY the summary text — no JSON, no markdown code fences, no preamble. "
        "Just the description."
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
