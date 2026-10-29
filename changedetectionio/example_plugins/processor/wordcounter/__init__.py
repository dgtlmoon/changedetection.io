"""
Example processor plugin - counts the words on a page, a change is when the count changes.

Copy this directory into your own pip package to start a processor plugin, see ../../README.md.
It is not active unless registered, nothing scans example_plugins/ for plugins.
"""
from changedetectionio.pluggy_interface import hookimpl

# The machine name, also used for processor_config_word_counter / processor_state_word_counter in the API
PROCESSOR_NAME = 'word_counter'


@hookimpl
def register_processor():
    from . import processor
    return {
        'processor_name': PROCESSOR_NAME,
        'processor_module': processor,
        'processor_class': processor.perform_site_check,
        'metadata': {
            'name': 'Word counter (example plugin)',
            'description': 'Counts the words on the page, a change is when the count changes',
            'processor_weight': 0,
        },
    }


@hookimpl
def get_api_watch_processor_state(watch, processor_name, context):
    """processor_state_word_counter in GET /api/v1/watch/<uuid> and GET /api/v1/watch, see api.yaml"""
    if processor_name != PROCESSOR_NAME:
        return None
    # processor.py stores this on the watch, in memory, so it's cheap enough for context='list'
    state = watch.get(f'processor_state_{PROCESSOR_NAME}') or {}
    return {'word_count': state.get('word_count')}
