import os
import time
from flask import url_for
from .util import set_original_response,  wait_for_all_checks, wait_for_notification_endpoint_output
from ..notification import valid_notification_formats
from loguru import  logger

def test_queue_system(client, live_server, measure_memory_usage, datastore_path):
    """Test that multiple workers can process queue concurrently without blocking each other"""
    # (pytest) Werkzeug's threaded server uses ThreadPoolExecutor with a default limit of around 40 threads (or min(32, os.cpu_count() + 4)).
    items = os.cpu_count() +3
    delay = 10
    # Auto-queue is off here.
    live_server.app.config['DATASTORE'].data['settings']['application']['all_paused'] = True

    test_urls = [
        f"{url_for('test_endpoint', _external=True)}?delay={delay}&id={i}&content=hello+test+content+{i}"
        for i in range(0, items)
    ]

    # Import 30 URLs to queue
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": "\r\n".join(test_urls)},
        follow_redirects=True
    )
    assert f"{items} Imported".encode('utf-8') in res.data

    # Start 30 workers and verify all are alive
    client.application.set_workers(items)

    start = time.time()
    res = client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)

    wait_for_all_checks(client)

    # all workers should be done in less than say 10 seconds (they take time to 'see' something is in the queue too)
    total_time = (time.time() - start)
    logger.debug(f"All workers finished {items} items in less than {delay} seconds per job. {total_time}s total")
    # if there was a bug in queue handler not running parallel, this would blow out to items*delay seconds
    assert total_time < delay + 10, f"All workers finished {items} items in less than {delay} seconds per job, total time {total_time}s"
