"""
Prompt construction for LLM evaluation calls.
Pure functions — no side effects, fully testable.
"""

from .bm25_trim import trim_to_relevant

SNAPSHOT_CONTEXT_CHARS = 3_000   # current page state excerpt sent alongside the diff


def _annotate_moved_lines(diff_text: str) -> str:
    """
    Pre-process a unified diff to mark lines that appear on both the + and - sides
    as [MOVED] rather than genuinely added/removed. This prevents the LLM from
    incorrectly classifying repositioned content as new or deleted.

    Lines are compared after stripping leading +/- and whitespace so that
    indentation changes don't prevent matching.
    """
    lines = diff_text.splitlines()
    added_texts   = {l[1:].strip().lower() for l in lines if l.startswith('+') and l[1:].strip()}
    removed_texts = {l[1:].strip().lower() for l in lines if l.startswith('-') and l[1:].strip()}
    moved_texts   = added_texts & removed_texts

    if not moved_texts:
        return diff_text

    result = []
    for line in lines:
        if line.startswith(('+', '-')):
            bare = line[1:].strip().lower()
            if bare in moved_texts:
                result.append(f'~{line[1:]}')  # ~ prefix = moved/reordered/trivial, skip
                continue
        result.append(line)
    return '\n'.join(result)


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
    parts.append(f"\nWhat changed (diff):\n{_annotate_moved_lines(diff)}")
    return '\n'.join(parts)


def build_change_summary_system_prompt() -> str:
    return (
        "You are a meticulous, accurate summariser of website changes for monitoring notifications.\n"
        "Your goal is to describe exactly what changed — never omit significant details, "
        "never add information that isn't in the diff, and never speculate.\n\n"
        "Rules for reading the diff:\n"
        "- Lines starting with + are genuinely new content. List them specifically.\n"
        "- Lines starting with - are genuinely removed content. List them specifically.\n"
        "- Lines starting with ~ have been PRE-IDENTIFIED as moved/reordered — "
        "the same text exists on both sides of the diff. Do NOT report ~ lines as added or removed. "
        "If many ~ lines exist, note briefly that some content was reordered.\n"
        "- NEVER mention standalone timestamps (e.g. '3 hours ago', '17 hours ago', 'Yesterday', "
        "'Today', '2 minutes ago', '1 hour ago') as added or removed items. They are not content. "
        "Completely discard any + or - line whose entire content is a timestamp like these. "
        "Do not list them. Do not count them. Pretend they do not exist in the diff.\n\n"
        "For content-heavy pages (news, listings, feeds): quote or paraphrase the specific new "
        "headlines, items, or entries that were added — do not collapse them into vague phrases "
        "like 'new articles were added' or 'section was expanded'.\n"
        "For large blocks of new text (full articles, documents, long paragraphs): briefly summarise "
        "the substance in 1-2 sentences capturing the key point — do not just repeat the title.\n\n"
        "Structure your response using these sections, in this fixed order — "
        "omit a section entirely if there is nothing to report for it:\n"
        "  Added: ...\n"
        "  Changed: ...\n"
        "  Removed: ...\n"
        "The Removed section MUST always be last. Never place removals before additions or changes.\n\n"
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
