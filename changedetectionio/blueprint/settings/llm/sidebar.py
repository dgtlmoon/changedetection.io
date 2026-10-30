"""The AI / LLM link in the left action sidebar, added through the same register_sidebar_items hook plugins use."""
from changedetectionio.plugin_api import hookimpl

# Feather's "cpu" chip (same outline and pins, https://feathericons.com) with "AI" drawn in the middle as
# lines rather than text, so it's crisp at 24px and doesn't depend on fonts. currentColor follows the theme
# and the active state like the Feather icons around it.
AI_CHIP_SVG = (
    '<svg class="action-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    # The chip and its pins
    '<rect x="4" y="4" width="16" height="16" rx="2" ry="2"/>'
    '<line x1="9" y1="1" x2="9" y2="4"/><line x1="15" y1="1" x2="15" y2="4"/>'
    '<line x1="9" y1="20" x2="9" y2="23"/><line x1="15" y1="20" x2="15" y2="23"/>'
    '<line x1="20" y1="9" x2="23" y2="9"/><line x1="20" y1="14" x2="23" y2="14"/>'
    '<line x1="1" y1="9" x2="4" y2="9"/><line x1="1" y1="14" x2="4" y2="14"/>'
    # "AI", a thinner line so the letters stay open
    '<path d="M8.6 15.4 10.7 8.6l2.1 6.8M9.3 13.2h2.8M15.4 8.6v6.8" stroke-width="1.6"/>'
    '</svg>'
)


@hookimpl
def register_sidebar_items(datastore):
    from flask_babel import gettext
    from changedetectionio.llm.evaluator import is_llm_features_disabled

    # LLM_FEATURES_DISABLED hides every AI surface, this link included
    if is_llm_features_disabled():
        return None
    return {
        'label': gettext('AI / LLM'),
        'title': gettext('AI / LLM settings'),
        'endpoint': 'settings.llm.llm_settings_page',
        'svg': AI_CHIP_SVG,
        'active_prefix': 'settings.llm.',
    }
