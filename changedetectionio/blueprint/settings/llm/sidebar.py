"""The AI / LLM link in the left action sidebar, added through the same register_sidebar_items hook plugins use."""
from changedetectionio.plugin_api import hookimpl


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
        'icon': 'cpu',
        'active_prefix': 'settings.llm.',
    }
