"""
changedetectionio.llm
~~~~~~~~~~~~~~~~~~~~~

LLM summary queue and workers.

Usage in flask_app.py
---------------------

    import changedetectionio.llm as llm

    # At module level alongside notification_q:
    llm_summary_q = llm.create_queue()

    # Inside changedetection_app(), after datastore is ready:
    llm.start_workers(
        app=app,
        datastore=datastore,
        llm_q=llm_summary_q,
        n_workers=int(os.getenv("LLM_WORKERS", "1")),
    )

Enqueueing a summary job (e.g. from the pluggy update_finalize hook)
---------------------------------------------------------------------

    if changed_detected and not processing_exception:
        llm_summary_q.put({
            'uuid':        watch_uuid,
            'snapshot_id': snapshot_id,
            'attempts':    0,
        })
"""

import queue
import threading
from loguru import logger


def create_queue() -> queue.Queue:
    """Return a plain Queue for LLM summary jobs. No maxsize — jobs are small dicts."""
    return queue.Queue()


def start_workers(app, datastore, llm_q: queue.Queue, n_workers: int = 1) -> None:
    """
    Start N LLM summary worker threads.

    Args:
        app:        Flask application instance (for app_context and exit event)
        datastore:  Application datastore
        llm_q:      Queue returned by create_queue()
        n_workers:  Number of parallel workers (default 1; increase for local Ollama)
    """
    from changedetectionio.llm.queue_worker import llm_summary_runner

    for i in range(n_workers):
        threading.Thread(
            target=llm_summary_runner,
            args=(i, app, datastore, llm_q),
            daemon=True,
            name=f"LLMSummaryWorker-{i}",
        ).start()

    logger.info(f"Started {n_workers} LLM summary worker(s)")
