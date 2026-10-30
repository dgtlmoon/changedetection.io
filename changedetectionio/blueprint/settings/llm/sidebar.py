"""The AI / LLM link in the left action sidebar, added through the same register_sidebar_items hook plugins use."""
from changedetectionio.plugin_api import hookimpl

# A simple octopus in the Feather icon style the rest of the sidebar uses: 24x24, 2px currentColor line,
# round caps, so it follows the theme and the active state. Many arms for many tools.
OCTOPUS_SVG = (
    '<svg class="action-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    # Head: a closed, round head on top (an open dome with straight legs reads as a ghost)
    '<ellipse cx="12" cy="8.3" rx="6.2" ry="5.3"/>'
    # Four wavy arms spreading out to the sides, curling at the tips
    '<path d="M7.6 12.4c-1.8 1.3-4.4.8-5 3-.3 1.2.9 1.9 1.8 1.2"/>'
    '<path d="M10.2 13.5c-.9 2.1-2.8 2.9-3.1 5-.2 1.3.8 2.2 1.9 1.5"/>'
    '<path d="M13.8 13.5c.9 2.1 2.8 2.9 3.1 5 .2 1.3-.8 2.2-1.9 1.5"/>'
    '<path d="M16.4 12.4c1.8 1.3 4.4.8 5 3 .3 1.2-.9 1.9-1.8 1.2"/>'
    # Eyes, solid dots without the outline
    '<circle cx="9.8" cy="8.2" r="1.05" fill="currentColor" stroke="none"/>'
    '<circle cx="14.2" cy="8.2" r="1.05" fill="currentColor" stroke="none"/>'
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
        'svg': OCTOPUS_SVG,
        'active_prefix': 'settings.llm.',
    }
