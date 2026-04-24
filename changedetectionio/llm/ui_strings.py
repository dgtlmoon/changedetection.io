"""
Shared UI placeholder strings for LLM fields.

Used by WTForms field definitions in forms.py and blueprint/tags/form.py.
Templates use their own _()-translated variants but should stay in sync with these.
"""

# llm_intent field — placeholder text for per-watch context
LLM_INTENT_WATCH_PLACEHOLDER = (
    "e.g. Alert me when the price drops below $300, or a new product is launched. "
    "Ignore footer and navigation changes."
)

# llm_intent field — placeholder text for tag/group context
LLM_INTENT_TAG_PLACEHOLDER = (
    "e.g. Flag price changes or new product launches across all watches in this group"
)

