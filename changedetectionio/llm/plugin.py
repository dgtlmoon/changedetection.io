"""
LLM plugin — provides settings tab and enqueues summary jobs on change detection.

Registered with the pluggy plugin manager at startup (flask_app.py).
The worker (llm/queue_worker.py) drains the queue asynchronously.
"""
from loguru import logger
from changedetectionio.pluggy_interface import hookimpl


def get_llm_settings(datastore):
    """Load LLM plugin settings with fallback to legacy datastore settings.

    Tries the plugin settings file (llm.json) first.
    Falls back to the old storage location in datastore.data['settings']['application']
    for users upgrading from a version before LLM became a first-class plugin.
    """
    from changedetectionio.pluggy_interface import load_plugin_settings
    settings = load_plugin_settings(datastore.datastore_path, 'llm')

    if settings.get('llm_connection') is not None:
        return settings

    # Legacy fallback: settings were stored in datastore application settings
    app_settings = datastore.data['settings']['application']
    connections_dict = app_settings.get('llm_connections') or {}
    connections_list = [
        {
            'connection_id':     k,
            'name':              v.get('name', ''),
            'model':             v.get('model', ''),
            'api_key':           v.get('api_key', ''),
            'api_base':          v.get('api_base', ''),
            'tokens_per_minute': int(v.get('tokens_per_minute', 0) or 0),
            'is_default':        bool(v.get('is_default', False)),
        }
        for k, v in connections_dict.items()
    ]

    return {
        'llm_connection':    connections_list,
        'llm_summary_prompt': app_settings.get('llm_summary_prompt', ''),
    }


def save_llm_settings(datastore, plugin_form):
    """Custom save handler — strips the ephemeral new_connection staging fields
    so they are never persisted to llm.json."""
    from changedetectionio.pluggy_interface import save_plugin_settings
    data = {
        'llm_connection':         plugin_form.llm_connection.data,
        'llm_summary_prompt':     plugin_form.llm_summary_prompt.data or '',
        'llm_diff_context_lines': plugin_form.llm_diff_context_lines.data or 2,
    }
    save_plugin_settings(datastore.datastore_path, 'llm', data)


class LLMQueuePlugin:
    """Enqueues LLM summary jobs on successful change detection and provides settings tab."""

    def __init__(self, llm_q):
        self.llm_q = llm_q

    @hookimpl
    def plugin_settings_tab(self):
        from changedetectionio.llm.settings_form import LLMSettingsForm
        return {
            'plugin_id':     'llm',
            'tab_label':     'LLM',
            'form_class':    LLMSettingsForm,
            'template_path': 'settings-llm.html',
            'save_fn':       save_llm_settings,
        }

    @hookimpl
    def update_finalize(self, update_handler, watch, datastore, processing_exception,
                        changed_detected=False, snapshot_id=None):
        """Queue an LLM summary job when a change was successfully detected."""

        if not changed_detected or processing_exception or not snapshot_id:
            return

        if watch is None:
            return

        # Need ≥2 history entries — first entry has nothing to diff against
        if watch.history_n < 2:
            return

        # Only queue when at least one LLM connection is configured
        llm_settings = get_llm_settings(datastore)
        has_connection = bool(
            llm_settings.get('llm_connection')
            or datastore.data['settings']['application'].get('llm_api_key')   # legacy
            or datastore.data['settings']['application'].get('llm_model')     # legacy
            or watch.get('llm_api_key')
            or watch.get('llm_model')
        )
        if not has_connection:
            return

        uuid = watch.get('uuid')
        self.llm_q.put({'uuid': uuid, 'snapshot_id': snapshot_id, 'attempts': 0})
        logger.debug(f"LLM: queued summary for uuid={uuid} snapshot={snapshot_id}")
