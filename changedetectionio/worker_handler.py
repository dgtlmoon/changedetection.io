"""
Worker management module for changedetection.io

Handles asynchronous workers for dynamic worker scaling.
Sync worker support has been removed in favor of async-only architecture.
"""

import asyncio
import os
import threading
import time
from loguru import logger

# Global worker state
running_async_tasks = []
async_loop = None
async_loop_thread = None

# Track currently processing UUIDs for async workers
currently_processing_uuids = set()

# Configuration - async workers only
USE_ASYNC_WORKERS = True


def start_async_event_loop():
    """Start a dedicated event loop for async workers in a separate thread"""
    global async_loop
    logger.info("Starting async event loop for workers")
    
    try:
        # Create a new event loop for this thread
        async_loop = asyncio.new_event_loop()
        # Set it as the event loop for this thread
        asyncio.set_event_loop(async_loop)
        
        logger.debug(f"Event loop created and set: {async_loop}")
        
        # Run the event loop forever
        async_loop.run_forever()
    except Exception as e:
        logger.error(f"Async event loop error: {e}")
    finally:
        # Clean up
        if async_loop and not async_loop.is_closed():
            async_loop.close()
        async_loop = None
        logger.info("Async event loop stopped")


def start_async_workers(n_workers, update_q, notification_q, app, datastore):
    """Start the async worker management system"""
    global async_loop_thread, async_loop, running_async_tasks, currently_processing_uuids
    
    # Clear any stale UUID tracking state
    currently_processing_uuids.clear()
    
    # Start the event loop in a separate thread
    async_loop_thread = threading.Thread(target=start_async_event_loop, daemon=True)
    async_loop_thread.start()
    
    # Wait for the loop to be available (with timeout for safety)
    max_wait_time = 5.0
    wait_start = time.time()
    while async_loop is None and (time.time() - wait_start) < max_wait_time:
        time.sleep(0.1)
    
    if async_loop is None:
        logger.error("Failed to start async event loop within timeout")
        return
    
    # Additional brief wait to ensure loop is running
    time.sleep(0.2)
    
    # Start async workers
    logger.info(f"Starting {n_workers} async workers")
    for i in range(n_workers):
        try:
            # Use a factory function to create named worker coroutines
            def create_named_worker(worker_id):
                async def named_worker():
                    task = asyncio.current_task()
                    if task:
                        task.set_name(f"async-worker-{worker_id}")
                    return await start_single_async_worker(worker_id, update_q, notification_q, app, datastore)
                return named_worker()
            
            task_future = asyncio.run_coroutine_threadsafe(create_named_worker(i), async_loop)
            running_async_tasks.append(task_future)
        except RuntimeError as e:
            logger.error(f"Failed to start async worker {i}: {e}")
            continue


async def start_single_async_worker(worker_id, update_q, notification_q, app, datastore):
    """Start a single async worker with auto-restart capability"""
    from changedetectionio.async_update_worker import async_update_worker
    
    # Check if we're in pytest environment - if so, be more gentle with logging
    import os
    in_pytest = "pytest" in os.sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    
    while not app.config.exit.is_set():
        try:
            if not in_pytest:
                logger.info(f"Starting async worker {worker_id}")
            await async_update_worker(worker_id, update_q, notification_q, app, datastore)
            # If we reach here, worker exited cleanly
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
    global running_async_tasks
    
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


def remove_worker():
    """Remove an async worker (for dynamic scaling)"""
    global running_async_tasks
    
    if not running_async_tasks:
        return False
        
    # Cancel the last worker
    task_future = running_async_tasks.pop()
    task_future.cancel()
    logger.info(f"Removed async worker, {len(running_async_tasks)} workers remaining")
    return True


def get_worker_count():
    """Get current number of async workers"""
    return len(running_async_tasks)


def get_running_uuids():
    """Get list of UUIDs currently being processed by async workers"""
    return list(currently_processing_uuids)


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
    """Queue an item for async queue processing"""
    if async_loop and not async_loop.is_closed():
        try:
            # For async queue, schedule the put operation
            asyncio.run_coroutine_threadsafe(update_q.put(item), async_loop)
        except RuntimeError as e:
            logger.error(f"Failed to queue item: {e}")
    else:
        logger.error("Async loop not available or closed for queueing item")


def shutdown_workers():
    """Shutdown all async workers fast and aggressively"""
    global async_loop, async_loop_thread, running_async_tasks
    
    # Check if we're in pytest environment - if so, be more gentle with logging
    import os
    in_pytest = "pytest" in os.sys.modules or "PYTEST_CURRENT_TEST" in os.environ
    
    if not in_pytest:
        logger.info("Fast shutdown of async workers initiated...")
    
    # Cancel all async tasks immediately
    for task_future in running_async_tasks:
        if not task_future.done():
            task_future.cancel()
    
    # Stop the async event loop immediately
    if async_loop and not async_loop.is_closed():
        try:
            async_loop.call_soon_threadsafe(async_loop.stop)
        except RuntimeError:
            # Loop might already be stopped
            pass
        
    running_async_tasks.clear()
    async_loop = None
        
    # Give async thread minimal time to finish, then continue
    if async_loop_thread and async_loop_thread.is_alive():
        async_loop_thread.join(timeout=1.0)  # Only 1 second timeout
        if async_loop_thread.is_alive() and not in_pytest:
            logger.info("Async thread still running after timeout - continuing with shutdown")
        async_loop_thread = None
    
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
    global running_async_tasks
    
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


def get_worker_status():
    """Get status information about async workers"""
    return {
        'worker_type': 'async',
        'worker_count': get_worker_count(),
        'running_uuids': get_running_uuids(),
        'async_loop_running': async_loop is not None,
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
    global running_async_tasks
    
    current_count = get_worker_count()
    
    if current_count == expected_count:
        return {
            'status': 'healthy',
            'expected_count': expected_count,
            'actual_count': current_count,
            'message': f'All {expected_count} async workers running'
        }
    
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