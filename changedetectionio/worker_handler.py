"""
Worker management module for changedetection.io

Handles asynchronous workers for dynamic worker scaling.
Each worker runs in its own thread with its own event loop for isolation.
"""

import asyncio
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from loguru import logger

# Global worker state - each worker has its own thread and event loop
worker_threads = []  # List of WorkerThread objects

# Track currently processing UUIDs for async workers - maps {uuid: worker_id}
currently_processing_uuids = {}

# Configuration - async workers only
USE_ASYNC_WORKERS = True

# Custom ThreadPoolExecutor for queue operations with named threads
# Scale executor threads with FETCH_WORKERS to avoid bottleneck at high concurrency
_max_executor_workers = max(50, int(os.getenv("FETCH_WORKERS", "10")))
queue_executor = ThreadPoolExecutor(
    max_workers=_max_executor_workers,
    thread_name_prefix="QueueGetter-"
)


class WorkerThread:
    """Container for a worker thread with its own event loop"""
    def __init__(self, worker_id, update_q, notification_q, app, datastore):
        self.worker_id = worker_id
        self.update_q = update_q
        self.notification_q = notification_q
        self.app = app
        self.datastore = datastore
        self.thread = None
        self.loop = None
        self.running = False

    def run(self):
        """Run the worker in its own event loop"""
        try:
            # Create a new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.running = True

            # Run the worker coroutine
            self.loop.run_until_complete(
                start_single_async_worker(
                    self.worker_id,
                    self.update_q,
                    self.notification_q,
                    self.app,
                    self.datastore,
                    queue_executor
                )
            )
        except asyncio.CancelledError:
            # Normal shutdown - worker was cancelled
            import os
            in_pytest = "pytest" in os.sys.modules or "PYTEST_CURRENT_TEST" in os.environ
            if not in_pytest:
                logger.info(f"Worker {self.worker_id} shutting down gracefully")
        except RuntimeError as e:
            # Ignore expected shutdown errors
            if "Event loop stopped" not in str(e) and "Event loop is closed" not in str(e):
                logger.error(f"Worker {self.worker_id} runtime error: {e}")
        except Exception as e:
            logger.error(f"Worker {self.worker_id} thread error: {e}")
        finally:
            # Clean up
            if self.loop and not self.loop.is_closed():
                self.loop.close()
            self.running = False
            self.loop = None

    def start(self):
        """Start the worker thread"""
        self.thread = threading.Thread(
            target=self.run,
            daemon=True,
            name=f"PageFetchAsyncUpdateWorker-{self.worker_id}"
        )
        self.thread.start()

    def stop(self):
        """Stop the worker thread"""
        if self.loop and self.running:
            try:
                # Signal the loop to stop
                self.loop.call_soon_threadsafe(self.loop.stop)
            except RuntimeError:
                pass

        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)


def start_async_workers(n_workers, update_q, notification_q, app, datastore):
    """Start async workers, each with its own thread and event loop for isolation"""
    global worker_threads, currently_processing_uuids

    # Clear any stale state
    currently_processing_uuids.clear()

    # Start each worker in its own thread with its own event loop
    logger.info(f"Starting {n_workers} async workers (isolated threads)")
    for i in range(n_workers):
        try:
            worker = WorkerThread(i, update_q, notification_q, app, datastore)
            worker.start()
            worker_threads.append(worker)
            # No sleep needed - threads start independently and asynchronously
        except Exception as e:
            logger.error(f"Failed to start async worker {i}: {e}")
            continue


async def start_single_async_worker(worker_id, update_q, notification_q, app, datastore, executor=None):
    """Start a single async worker with auto-restart capability"""
    from changedetectionio.async_update_worker import async_update_worker

    # Check if we're in pytest environment - if so, be more gentle with logging
    import os
    in_pytest = "pytest" in os.sys.modules or "PYTEST_CURRENT_TEST" in os.environ

    while not app.config.exit.is_set():
        try:
            result = await async_update_worker(worker_id, update_q, notification_q, app, datastore, executor)

            if result == "restart":
                # Worker requested restart - immediately loop back and restart
                if not in_pytest:
                    logger.debug(f"Async worker {worker_id} restarting")
                continue
            else:
                # Worker exited cleanly (shutdown)
                if not in_pytest:
                    logger.info(f"Async worker {worker_id} exited cleanly")
                break

        except asyncio.CancelledError:
            # Task was cancelled (normal shutdown)
            if not in_pytest:
                logger.info(f"Async worker {worker_id} cancelled")
            break
        except Exception as e:
            logger.error(f"Async worker {worker_id} crashed: {e}")
            if not in_pytest:
                logger.info(f"Restarting async worker {worker_id} in 5 seconds...")
            await asyncio.sleep(5)

    if not in_pytest:
        logger.info(f"Async worker {worker_id} shutdown complete")


def start_workers(n_workers, update_q, notification_q, app, datastore):
    """Start async workers - sync workers are deprecated"""
    start_async_workers(n_workers, update_q, notification_q, app, datastore)


def add_worker(update_q, notification_q, app, datastore):
    """Add a new async worker (for dynamic scaling)"""
    global worker_threads

    # Reuse lowest available ID to prevent unbounded growth over time
    used_ids = {w.worker_id for w in worker_threads}
    worker_id = 0
    while worker_id in used_ids:
        worker_id += 1
    logger.info(f"Adding async worker {worker_id}")

    try:
        worker = WorkerThread(worker_id, update_q, notification_q, app, datastore)
        worker.start()
        worker_threads.append(worker)
        return True
    except Exception as e:
        logger.error(f"Failed to add worker {worker_id}: {e}")
        return False


def remove_worker():
    """Remove an async worker (for dynamic scaling)"""
    global worker_threads

    if not worker_threads:
        return False

    # Stop the last worker
    worker = worker_threads.pop()
    worker.stop()
    logger.info(f"Removed async worker, {len(worker_threads)} workers remaining")
    return True


def get_worker_count():
    """Get current number of async workers"""
    return len(worker_threads)


def get_running_uuids():
    """Get list of UUIDs currently being processed by async workers"""
    return list(currently_processing_uuids.keys())


def set_uuid_processing(uuid, worker_id=None, processing=True):
    """Mark a UUID as being processed or completed by a specific worker"""
    global currently_processing_uuids
    if processing:
        currently_processing_uuids[uuid] = worker_id
        logger.debug(f"Worker {worker_id} started processing UUID: {uuid}")
    else:
        currently_processing_uuids.pop(uuid, None)
        logger.debug(f"Worker {worker_id} finished processing UUID: {uuid}")


def is_watch_running(watch_uuid):
    """Check if a specific watch is currently being processed by any worker"""
    return watch_uuid in currently_processing_uuids


def is_watch_running_by_another_worker(watch_uuid, current_worker_id):
    """Check if a specific watch is currently being processed by a different worker"""
    if watch_uuid not in currently_processing_uuids:
        return False
    processing_worker_id = currently_processing_uuids[watch_uuid]
    return processing_worker_id != current_worker_id


def queue_item_async_safe(update_q, item, silent=False):
    """Bulletproof queue operation with comprehensive error handling"""
    item_uuid = 'unknown'

    try:
        # Safely extract UUID for logging
        if hasattr(item, 'item') and isinstance(item.item, dict):
            item_uuid = item.item.get('uuid', 'unknown')
    except Exception as uuid_e:
        logger.critical(f"CRITICAL: Failed to extract UUID from queue item: {uuid_e}")

    # Validate inputs
    if not update_q:
        logger.critical(f"CRITICAL: Queue is None/invalid for item {item_uuid}")
        return False

    if not item:
        logger.critical(f"CRITICAL: Item is None/invalid")
        return False

    # Attempt queue operation with multiple fallbacks
    try:
        # Primary: Use sync interface (thread-safe)
        success = update_q.put(item, block=True, timeout=5.0)
        if success is False:  # Explicit False return means failure
            logger.critical(f"CRITICAL: Queue.put() returned False for item {item_uuid}")
            return False

        if not silent:
            logger.trace(f"Successfully queued item: {item_uuid}")
        return True
        
    except Exception as e:
        logger.critical(f"CRITICAL: Exception during queue operation for item {item_uuid}: {type(e).__name__}: {e}")
        
        # Secondary: Attempt queue health check
        try:
            queue_size = update_q.qsize()
            is_empty = update_q.empty()
            logger.critical(f"CRITICAL: Queue health - size: {queue_size}, empty: {is_empty}")
        except Exception as health_e:
            logger.critical(f"CRITICAL: Queue health check failed: {health_e}")
        
        # Log queue type for debugging
        try:
            logger.critical(f"CRITICAL: Queue type: {type(update_q)}, has sync_q: {hasattr(update_q, 'sync_q')}")
        except Exception:
            logger.critical(f"CRITICAL: Cannot determine queue type")
        
        return False


def shutdown_workers():
    """Shutdown all async workers fast and aggressively"""
    global worker_threads

    # Check if we're in pytest environment - if so, be more gentle with logging
    import os
    in_pytest = "pytest" in os.sys.modules or "PYTEST_CURRENT_TEST" in os.environ

    if not in_pytest:
        logger.info("Fast shutdown of async workers initiated...")

    # Stop all worker threads
    for worker in worker_threads:
        worker.stop()

    worker_threads.clear()

    if not in_pytest:
        logger.info("Async workers fast shutdown complete")




def adjust_async_worker_count(new_count, update_q=None, notification_q=None, app=None, datastore=None):
    """
    Dynamically adjust the number of async workers.

    Args:
        new_count: Target number of workers
        update_q, notification_q, app, datastore: Required for adding new workers

    Returns:
        dict: Status of the adjustment operation
    """
    global worker_threads

    current_count = get_worker_count()

    if new_count == current_count:
        return {
            'status': 'no_change',
            'message': f'Worker count already at {current_count}',
            'current_count': current_count
        }

    if new_count > current_count:
        # Add workers
        workers_to_add = new_count - current_count
        logger.info(f"Adding {workers_to_add} async workers (from {current_count} to {new_count})")

        if not all([update_q, notification_q, app, datastore]):
            return {
                'status': 'error',
                'message': 'Missing required parameters to add workers',
                'current_count': current_count
            }

        for i in range(workers_to_add):
            add_worker(update_q, notification_q, app, datastore)

        return {
            'status': 'success',
            'message': f'Added {workers_to_add} workers',
            'previous_count': current_count,
            'current_count': len(worker_threads)
        }

    else:
        # Remove workers
        workers_to_remove = current_count - new_count
        logger.info(f"Removing {workers_to_remove} async workers (from {current_count} to {new_count})")

        removed_count = 0
        for _ in range(workers_to_remove):
            if remove_worker():
                removed_count += 1

        return {
            'status': 'success',
            'message': f'Removed {removed_count} workers',
            'previous_count': current_count,
            'current_count': current_count - removed_count
        }


def get_worker_status():
    """Get status information about async workers"""
    return {
        'worker_type': 'async',
        'worker_count': get_worker_count(),
        'running_uuids': get_running_uuids(),
        'active_threads': sum(1 for w in worker_threads if w.thread and w.thread.is_alive()),
    }


def check_worker_health(expected_count, update_q=None, notification_q=None, app=None, datastore=None):
    """
    Check if the expected number of async workers are running and restart any missing ones.

    Args:
        expected_count: Expected number of workers
        update_q, notification_q, app, datastore: Required for restarting workers

    Returns:
        dict: Health check results
    """
    global worker_threads

    current_count = get_worker_count()

    # Check which workers are actually alive
    alive_count = sum(1 for w in worker_threads if w.thread and w.thread.is_alive())

    if alive_count == expected_count:
        return {
            'status': 'healthy',
            'expected_count': expected_count,
            'actual_count': alive_count,
            'message': f'All {expected_count} async workers running'
        }

    # Find dead workers
    dead_workers = []
    for i, worker in enumerate(worker_threads[:]):
        if not worker.thread or not worker.thread.is_alive():
            dead_workers.append(i)
            logger.warning(f"Async worker {worker.worker_id} thread is dead")

    # Remove dead workers from tracking
    for i in reversed(dead_workers):
        if i < len(worker_threads):
            worker_threads.pop(i)

    missing_workers = expected_count - alive_count
    restarted_count = 0

    if missing_workers > 0 and all([update_q, notification_q, app, datastore]):
        logger.info(f"Restarting {missing_workers} crashed async workers")

        for i in range(missing_workers):
            if add_worker(update_q, notification_q, app, datastore):
                restarted_count += 1

    return {
        'status': 'repaired' if restarted_count > 0 else 'degraded',
        'expected_count': expected_count,
        'actual_count': alive_count,
        'dead_workers': len(dead_workers),
        'restarted_workers': restarted_count,
        'message': f'Found {len(dead_workers)} dead workers, restarted {restarted_count}'
    }