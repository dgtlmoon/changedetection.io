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
    """Start a single async worker with auto-restart capability"""
    from changedetectionio.async_update_worker import async_update_worker
    
    while not app.config.exit.is_set():
        try:
            logger.info(f"Starting async worker {worker_id}")
            await async_update_worker(worker_id, update_q, notification_q, app, datastore)
            # If we reach here, worker exited cleanly
            logger.info(f"Async worker {worker_id} exited cleanly")
            break
        except asyncio.CancelledError:
            # Task was cancelled (normal shutdown)
            logger.info(f"Async worker {worker_id} cancelled")
            break
        except Exception as e:
            logger.error(f"Async worker {worker_id} crashed: {e}")
            logger.info(f"Restarting async worker {worker_id} in 5 seconds...")
            await asyncio.sleep(5)
    
    logger.info(f"Async worker {worker_id} shutdown complete")


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


def adjust_async_worker_count(new_count, update_q=None, notification_q=None, app=None, datastore=None):
    """
    Dynamically adjust the number of async workers.
    
    Args:
        new_count: Target number of workers
        update_q, notification_q, app, datastore: Required for adding new workers
    
    Returns:
        dict: Status of the adjustment operation
    """
    global running_async_tasks, running_update_threads
    
    current_count = get_worker_count()
    
    if new_count == current_count:
        return {
            'status': 'no_change',
            'message': f'Worker count already at {current_count}',
            'current_count': current_count
        }
    
    if USE_ASYNC_WORKERS:
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
                worker_id = len(running_async_tasks)
                task_future = asyncio.run_coroutine_threadsafe(
                    start_single_async_worker(worker_id, update_q, notification_q, app, datastore), 
                    async_loop
                )
                running_async_tasks.append(task_future)
            
            return {
                'status': 'success',
                'message': f'Added {workers_to_add} workers',
                'previous_count': current_count,
                'current_count': new_count
            }
            
        else:
            # Remove workers
            workers_to_remove = current_count - new_count
            logger.info(f"Removing {workers_to_remove} async workers (from {current_count} to {new_count})")
            
            removed_count = 0
            for _ in range(workers_to_remove):
                if running_async_tasks:
                    task_future = running_async_tasks.pop()
                    task_future.cancel()
                    # Wait for the task to actually stop
                    try:
                        task_future.result(timeout=5)  # 5 second timeout
                    except Exception:
                        pass  # Task was cancelled, which is expected
                    removed_count += 1
            
            return {
                'status': 'success',
                'message': f'Removed {removed_count} workers',
                'previous_count': current_count,
                'current_count': current_count - removed_count
            }
    else:
        # Sync workers - more complex to adjust dynamically
        return {
            'status': 'not_supported',
            'message': 'Dynamic worker adjustment not supported for sync workers',
            'current_count': current_count
        }


def get_worker_status():
    """Get status information about workers"""
    return {
        'worker_type': 'async' if USE_ASYNC_WORKERS else 'sync',
        'worker_count': get_worker_count(),
        'running_uuids': get_running_uuids(),
        'async_loop_running': async_loop is not None if USE_ASYNC_WORKERS else None,
    }


def check_worker_health(expected_count, update_q=None, notification_q=None, app=None, datastore=None):
    """
    Check if the expected number of workers are running and restart any missing ones.
    
    Args:
        expected_count: Expected number of workers
        update_q, notification_q, app, datastore: Required for restarting workers
    
    Returns:
        dict: Health check results
    """
    global running_async_tasks, running_update_threads
    
    current_count = get_worker_count()
    
    if current_count == expected_count:
        return {
            'status': 'healthy',
            'expected_count': expected_count,
            'actual_count': current_count,
            'message': f'All {expected_count} workers running'
        }
    
    if USE_ASYNC_WORKERS:
        # Check for crashed async workers
        dead_workers = []
        alive_count = 0
        
        for i, task_future in enumerate(running_async_tasks[:]):
            if task_future.done():
                try:
                    result = task_future.result()
                    dead_workers.append(i)
                    logger.warning(f"Async worker {i} completed unexpectedly")
                except Exception as e:
                    dead_workers.append(i)
                    logger.error(f"Async worker {i} crashed: {e}")
            else:
                alive_count += 1
        
        # Remove dead workers from tracking
        for i in reversed(dead_workers):
            if i < len(running_async_tasks):
                running_async_tasks.pop(i)
        
        missing_workers = expected_count - alive_count
        restarted_count = 0
        
        if missing_workers > 0 and all([update_q, notification_q, app, datastore]):
            logger.info(f"Restarting {missing_workers} crashed async workers")
            
            for i in range(missing_workers):
                worker_id = alive_count + i
                try:
                    task_future = asyncio.run_coroutine_threadsafe(
                        start_single_async_worker(worker_id, update_q, notification_q, app, datastore), 
                        async_loop
                    )
                    running_async_tasks.append(task_future)
                    restarted_count += 1
                except Exception as e:
                    logger.error(f"Failed to restart worker {worker_id}: {e}")
        
        return {
            'status': 'repaired' if restarted_count > 0 else 'degraded',
            'expected_count': expected_count,
            'actual_count': alive_count,
            'dead_workers': len(dead_workers),
            'restarted_workers': restarted_count,
            'message': f'Found {len(dead_workers)} dead workers, restarted {restarted_count}'
        }
    else:
        # For sync workers, just report the issue (harder to auto-restart)
        return {
            'status': 'degraded',
            'expected_count': expected_count,
            'actual_count': current_count,
            'message': f'Worker count mismatch: expected {expected_count}, got {current_count}'
        }