"""
Worker management module for changedetection.io

Handles both synchronous threaded workers and asynchronous workers,
providing a unified interface for dynamic worker scaling.
"""

import asyncio
import os
import threading
import time
from loguru import logger

# Global worker state
running_update_threads = []
running_async_tasks = []
async_loop = None
async_loop_thread = None

# Track currently processing UUIDs for async workers
currently_processing_uuids = set()

# Configuration
USE_ASYNC_WORKERS = True


def start_async_event_loop():
    """Start a dedicated event loop for async workers in a separate thread"""
    global async_loop
    logger.info("Starting async event loop for workers")
    
    async_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(async_loop)
    
    try:
        async_loop.run_forever()
    except Exception as e:
        logger.error(f"Async event loop error: {e}")
    finally:
        logger.info("Async event loop stopped")


def start_async_workers(n_workers, update_q, notification_q, app, datastore):
    """Start the async worker management system"""
    global async_loop_thread, async_loop, running_async_tasks, currently_processing_uuids
    
    # Clear any stale UUID tracking state
    currently_processing_uuids.clear()
    
    # Start the event loop in a separate thread
    async_loop_thread = threading.Thread(target=start_async_event_loop, daemon=True)
    async_loop_thread.start()
    
    # Wait a moment for the loop to start
    time.sleep(0.1)
    
    # Start async workers
    logger.info(f"Starting {n_workers} async workers")
    for i in range(n_workers):
        task_future = asyncio.run_coroutine_threadsafe(
            start_single_async_worker(i, update_q, notification_q, app, datastore), async_loop
        )
        running_async_tasks.append(task_future)


async def start_single_async_worker(worker_id, update_q, notification_q, app, datastore):
    """Start a single async worker"""
    from changedetectionio.async_update_worker import async_update_worker
    
    try:
        await async_update_worker(worker_id, update_q, notification_q, app, datastore)
    except Exception as e:
        logger.error(f"Async worker {worker_id} crashed: {e}")


def start_sync_workers(n_workers, update_q, notification_q, app, datastore):
    """Start traditional threaded workers"""
    global running_update_threads
    from changedetectionio import update_worker
    
    logger.info(f"Starting {n_workers} sync workers")
    for _ in range(n_workers):
        new_worker = update_worker.update_worker(update_q, notification_q, app, datastore)
        running_update_threads.append(new_worker)
        new_worker.start()


def start_workers(n_workers, update_q, notification_q, app, datastore):
    """Start workers based on configuration"""
    if USE_ASYNC_WORKERS:
        start_async_workers(n_workers, update_q, notification_q, app, datastore)
    else:
        start_sync_workers(n_workers, update_q, notification_q, app, datastore)


def add_worker(update_q, notification_q, app, datastore):
    """Add a new worker (for dynamic scaling)"""
    global running_async_tasks, running_update_threads
    
    if USE_ASYNC_WORKERS:
        if not async_loop:
            logger.error("Async loop not running, cannot add worker")
            return False
            
        worker_id = len(running_async_tasks)
        logger.info(f"Adding async worker {worker_id}")
        
        task_future = asyncio.run_coroutine_threadsafe(
            start_single_async_worker(worker_id, update_q, notification_q, app, datastore), async_loop
        )
        running_async_tasks.append(task_future)
        return True
    else:
        # Add sync worker
        from changedetectionio import update_worker
        logger.info(f"Adding sync worker {len(running_update_threads)}")
        
        new_worker = update_worker.update_worker(update_q, notification_q, app, datastore)
        running_update_threads.append(new_worker)
        new_worker.start()
        return True


def remove_worker():
    """Remove a worker (for dynamic scaling)"""
    global running_async_tasks, running_update_threads
    
    if USE_ASYNC_WORKERS:
        if not running_async_tasks:
            return False
            
        # Cancel the last worker
        task_future = running_async_tasks.pop()
        task_future.cancel()
        logger.info(f"Removed async worker, {len(running_async_tasks)} workers remaining")
        return True
    else:
        if not running_update_threads:
            return False
            
        # Stop the last worker
        worker = running_update_threads.pop()
        # Note: Graceful shutdown would require adding stop mechanism to update_worker
        logger.info(f"Removed sync worker, {len(running_update_threads)} workers remaining")
        return True


def get_worker_count():
    """Get current number of workers"""
    if USE_ASYNC_WORKERS:
        return len(running_async_tasks)
    else:
        return len(running_update_threads)


def get_running_uuids():
    """Get list of UUIDs currently being processed"""
    if USE_ASYNC_WORKERS:
        return list(currently_processing_uuids)
    else:
        running_uuids = []
        for t in running_update_threads:
            if hasattr(t, 'current_uuid') and t.current_uuid:
                running_uuids.append(t.current_uuid)
        return running_uuids


def set_uuid_processing(uuid, processing=True):
    """Mark a UUID as being processed or completed"""
    global currently_processing_uuids
    if processing:
        currently_processing_uuids.add(uuid)
        logger.debug(f"Started processing UUID: {uuid}")
    else:
        currently_processing_uuids.discard(uuid)
        logger.debug(f"Finished processing UUID: {uuid}")


def is_watch_running(watch_uuid):
    """Check if a specific watch is currently being processed"""
    return watch_uuid in get_running_uuids()


def queue_item_async_safe(update_q, item):
    """Queue an item in a way that works with both sync and async queues"""
    if USE_ASYNC_WORKERS and async_loop:
        # For async queue, schedule the put operation
        asyncio.run_coroutine_threadsafe(update_q.put(item), async_loop)
    else:
        # For sync queue, put directly
        update_q.put(item)


def shutdown_workers():
    """Shutdown all workers gracefully"""
    global async_loop, async_loop_thread, running_async_tasks, running_update_threads
    
    logger.info("Shutting down workers...")
    
    if USE_ASYNC_WORKERS:
        # Cancel all async tasks
        for task_future in running_async_tasks:
            task_future.cancel()
        running_async_tasks.clear()
        
        # Stop the async event loop
        if async_loop:
            async_loop.call_soon_threadsafe(async_loop.stop)
            async_loop = None
            
        # Wait for the async thread to finish
        if async_loop_thread and async_loop_thread.is_alive():
            async_loop_thread.join(timeout=5)
            async_loop_thread = None
    else:
        # Stop sync workers
        for worker in running_update_threads:
            # Note: Would need to add proper stop mechanism to update_worker
            pass
        running_update_threads.clear()
    
    logger.info("Workers shutdown complete")


def get_worker_status():
    """Get status information about workers"""
    return {
        'worker_type': 'async' if USE_ASYNC_WORKERS else 'sync',
        'worker_count': get_worker_count(),
        'running_uuids': get_running_uuids(),
        'async_loop_running': async_loop is not None if USE_ASYNC_WORKERS else None,
    }