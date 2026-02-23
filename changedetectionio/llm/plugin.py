"""
LLM queue plugin — enqueues an LLM summary job whenever a change is detected.

Registered with the pluggy plugin manager at startup (flask_app.py).
The worker (llm/queue_worker.py) drains the queue asynchronously.
"""
from loguru import logger
from changedetectionio.pluggy_interface import hookimpl


class LLMQueuePlugin:
    """Enqueues LLM summary jobs on successful change detection."""

    def __init__(self, llm_q):
        self.llm_q = llm_q

    @hookimpl
    def update_finalize(self, update_handler, watch, datastore, processing_exception,
                        changed_detected=False, snapshot_id=None):
        """Queue an LLM summary job when a change was successfully detected."""

        # Only act on successful changes with a known snapshot
        if not changed_detected or processing_exception or not snapshot_id:
            return

        if watch is None:
            return

        # Need ≥2 history entries — first entry has nothing to diff against
        if watch.history_n < 2:
            return

        # Only queue when at least one LLM connection is configured
        app_settings = datastore.data['settings']['application']
        has_connection = (
            app_settings.get('llm_connections')
            or app_settings.get('llm_api_key')
            or app_settings.get('llm_model')
            or watch.get('llm_api_key')
            or watch.get('llm_model')
        )
        if not has_connection:
            return

        uuid = watch.get('uuid')
        self.llm_q.put({'uuid': uuid, 'snapshot_id': snapshot_id, 'attempts': 0})
        logger.debug(f"LLM: queued summary for uuid={uuid} snapshot={snapshot_id}")
