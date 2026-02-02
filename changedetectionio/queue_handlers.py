from blinker import signal
from loguru import logger
from typing import Dict, List, Any, Optional
import heapq
import queue
import threading

# Janus is no longer required - we use pure threading.Queue for multi-loop support
# try:
#     import janus
# except ImportError:
#     pass  # Not needed anymore


class RecheckPriorityQueue:
    """
    Thread-safe priority queue supporting multiple async event loops.

    ARCHITECTURE:
    - Multiple async workers, each with its own event loop in its own thread
    - Hybrid sync/async design for maximum scalability
    - Sync interface for ticker thread (threading.Queue)
    - Async interface for workers (asyncio.Event - NO executor threads!)

    SCALABILITY:
    - Scales to 100-200+ workers without executor thread exhaustion
    - Async workers wait on asyncio.Event (pure coroutines, no threads)
    - Sync callers use threading.Queue (backward compatible)

    WHY NOT JANUS:
    - Janus binds to ONE event loop at creation time
    - Our architecture has 15+ workers, each with separate event loops
    - Workers in different threads/loops cannot share janus async interface

    WHY NOT RUN_IN_EXECUTOR:
    - With 200 workers, run_in_executor() would block 200 threads
    - Exhausts ThreadPoolExecutor, starves Flask HTTP handlers
    - Pure async approach uses 0 threads while waiting
    """

    def __init__(self, maxsize: int = 0):
        try:
            import asyncio

            # Sync interface: threading.Queue for ticker thread and Flask routes
            self._notification_queue = queue.Queue(maxsize=maxsize if maxsize > 0 else 0)

            # Priority storage - thread-safe
            self._priority_items = []
            self._lock = threading.RLock()

            # No event signaling needed - pure polling approach
            # Workers check queue every 50ms (latency acceptable: 0-500ms)
            # Scales to 1000+ workers: each sleeping worker = ~4KB coroutine, not thread

            # Signals for UI updates
            self.queue_length_signal = signal('queue_length')

            logger.debug("RecheckPriorityQueue initialized successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to initialize RecheckPriorityQueue: {str(e)}")
            raise
    
    # SYNC INTERFACE (for ticker thread)
    def put(self, item, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync put with priority ordering"""
        logger.trace(f"RecheckQueue.put() called for item: {self._get_item_uuid(item)}, block={block}, timeout={timeout}")
        try:
            # CRITICAL: Add to both priority storage AND notification queue atomically
            # to prevent desynchronization where item exists but no notification
            with self._lock:
                heapq.heappush(self._priority_items, item)

                # Add notification - use blocking with timeout for safety
                # Notification queue is unlimited size, so should never block in practice
                # but timeout ensures we detect any unexpected issues (deadlock, etc)
                try:
                    self._notification_queue.put(True, block=True, timeout=5.0)
                except Exception as notif_e:
                    # Notification failed - MUST remove from priority_items to keep in sync
                    # This prevents "Priority queue inconsistency" errors in get()
                    logger.critical(f"CRITICAL: Notification queue put failed, removing from priority_items: {notif_e}")
                    self._priority_items.remove(item)
                    heapq.heapify(self._priority_items)
                    raise  # Re-raise to be caught by outer exception handler

            # Signal emission after successful queue - log but don't fail the operation
            # Item is already safely queued, so signal failure shouldn't affect queue state
            try:
                self._emit_put_signals(item)
            except Exception as signal_e:
                logger.error(f"Failed to emit put signals but item queued successfully: {signal_e}")

            logger.trace(f"Successfully queued item: {self._get_item_uuid(item)}")
            return True

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to put item {self._get_item_uuid(item)}: {type(e).__name__}: {str(e)}")
            # Item should have been cleaned up in the inner try/except if notification failed
            return False
    
    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get with priority ordering"""
        logger.trace(f"RecheckQueue.get() called, block={block}, timeout={timeout}")
        import queue as queue_module
        try:
            # Wait for notification (this doesn't return the actual item, just signals availability)
            self._notification_queue.get(block=block, timeout=timeout)

            # Get highest priority item
            with self._lock:
                if not self._priority_items:
                    logger.critical(f"CRITICAL: Queue notification received but no priority items available")
                    raise Exception("Priority queue inconsistency")
                item = heapq.heappop(self._priority_items)

            # Signal emission after successful retrieval - log but don't lose the item
            # Item is already retrieved, so signal failure shouldn't affect queue state
            try:
                self._emit_get_signals()
            except Exception as signal_e:
                logger.error(f"Failed to emit get signals but item retrieved successfully: {signal_e}")

            logger.trace(f"RecheckQueue.get() successfully retrieved item: {self._get_item_uuid(item)}")
            return item

        except queue_module.Empty:
            # Queue is empty with timeout - expected behavior
            logger.trace(f"RecheckQueue.get() timed out - queue is empty (timeout={timeout})")
            raise  # noqa
        except Exception as e:
            # Re-raise without logging - caller (worker) will handle and log appropriately
            logger.trace(f"RecheckQueue.get() failed with exception: {type(e).__name__}: {str(e)}")
            raise
    
    # ASYNC INTERFACE (for workers)
    async def async_put(self, item, executor=None):
        """Async put with priority ordering - uses thread pool to avoid blocking

        Args:
            item: Item to add to queue
            executor: Optional ThreadPoolExecutor. If None, uses default pool.
        """
        logger.trace(f"RecheckQueue.async_put() called for item: {self._get_item_uuid(item)}, executor={executor}")
        import asyncio
        try:
            # Use run_in_executor to call sync put without blocking event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                executor,  # Use provided executor or default
                lambda: self.put(item, block=True, timeout=5.0)
            )

            logger.trace(f"RecheckQueue.async_put() successfully queued item: {self._get_item_uuid(item)}")
            return result

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put item {self._get_item_uuid(item)}: {str(e)}")
            return False

    async def async_get(self, executor=None, timeout=0.9):
        """
        Pure async polling - NO executor threads consumed!

        SCALABILITY: With 2000 workers, this approach uses:
        - 0 threads while waiting (pure coroutine suspension via asyncio.sleep)
        - vs run_in_executor which would block 2000 threads = executor exhaustion

        POLLING: Checks queue every 50ms (latency: 0-50ms, acceptable for web monitoring)

        MULTI-LOOP SUPPORT: Works across multiple event loops since each worker
        has its own loop in its own thread. No event signaling = no loop binding issues.

        Args:
            executor: Ignored (kept for API compatibility with old code)
            timeout: Maximum time to wait in seconds (default 0.9s)

        Returns:
            Item from queue

        Raises:
            queue.Empty: If timeout expires with no item available
        """
        logger.trace(f"RecheckQueue.async_get() called, timeout={timeout}")
        import asyncio

        end_time = asyncio.get_event_loop().time() + timeout

        while True:
            # Try to get item (non-blocking, thread-safe)
            with self._lock:
                if self._priority_items:
                    item = heapq.heappop(self._priority_items)

                    # Drain sync notification queue to keep in sync
                    try:
                        self._notification_queue.get_nowait()
                    except queue.Empty:
                        pass

                    # Emit signals
                    try:
                        self._emit_get_signals()
                    except Exception as signal_e:
                        logger.error(f"Failed to emit get signals but item retrieved successfully: {signal_e}")

                    logger.trace(f"RecheckQueue.async_get() successfully retrieved item: {self._get_item_uuid(item)}")
                    return item

            # No item - check timeout
            remaining = end_time - asyncio.get_event_loop().time()
            if remaining <= 0:
                logger.trace(f"RecheckQueue.async_get() timed out - queue is empty")
                raise queue.Empty()

            # Sleep before next check (pure coroutine suspension - no thread blocked!)
            # 50ms poll interval: workers check queue 20 times/sec
            # With 2000 workers: 2000 × 4KB = 8MB RAM (vs 2000 threads = 16GB)
            sleep_time = min(0.05, remaining)  # 50ms or remaining timeout
            await asyncio.sleep(sleep_time)
    
    # UTILITY METHODS
    def qsize(self) -> int:
        """Get current queue size"""
        try:
            with self._lock:
                return len(self._priority_items)
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get queue size: {str(e)}")
            return 0
    
    def empty(self) -> bool:
        """Check if queue is empty"""
        return self.qsize() == 0

    def get_queued_uuids(self) -> list:
        """Get list of all queued UUIDs efficiently with single lock"""
        try:
            with self._lock:
                return [item.item['uuid'] for item in self._priority_items if hasattr(item, 'item') and 'uuid' in item.item]
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get queued UUIDs: {str(e)}")
            return []

    def clear(self):
        """Clear all items from both priority storage and notification queue"""
        try:
            with self._lock:
                # Clear priority items
                self._priority_items.clear()

                # Drain all notifications to prevent stale notifications
                # This is critical for test cleanup to prevent queue desynchronization
                drained = 0
                while not self._notification_queue.empty():
                    try:
                        self._notification_queue.get_nowait()
                        drained += 1
                    except queue.Empty:
                        break

                if drained > 0:
                    logger.debug(f"Cleared queue: removed {drained} notifications")

            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to clear queue: {str(e)}")
            return False

    def close(self):
        """Close the queue"""
        try:
            # Nothing to close for threading.Queue
            logger.debug("RecheckPriorityQueue closed successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to close RecheckPriorityQueue: {str(e)}")
    
    # COMPATIBILITY METHODS (from original implementation)
    @property
    def queue(self):
        """Provide compatibility with original queue access"""
        try:
            with self._lock:
                return list(self._priority_items)
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get queue list: {str(e)}")
            return []
    
    def get_uuid_position(self, target_uuid: str) -> Dict[str, Any]:
        """Find position of UUID in queue"""
        try:
            with self._lock:
                queue_list = list(self._priority_items)
                total_items = len(queue_list)
                
                if total_items == 0:
                    return {'position': None, 'total_items': 0, 'priority': None, 'found': False}
                
                # Find target item
                for item in queue_list:
                    if (hasattr(item, 'item') and isinstance(item.item, dict) and 
                        item.item.get('uuid') == target_uuid):
                        
                        # Count items with higher priority
                        position = sum(1 for other in queue_list if other.priority < item.priority)
                        return {
                            'position': position,
                            'total_items': total_items, 
                            'priority': item.priority,
                            'found': True
                        }
                
                return {'position': None, 'total_items': total_items, 'priority': None, 'found': False}
                
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get UUID position for {target_uuid}: {str(e)}")
            return {'position': None, 'total_items': 0, 'priority': None, 'found': False}
    
    def get_all_queued_uuids(self, limit: Optional[int] = None, offset: int = 0) -> Dict[str, Any]:
        """Get all queued UUIDs with pagination"""
        try:
            with self._lock:
                queue_list = sorted(self._priority_items)  # Sort by priority
                total_items = len(queue_list)
                
                if total_items == 0:
                    return {'items': [], 'total_items': 0, 'returned_items': 0, 'has_more': False}
                
                # Apply pagination
                end_idx = min(offset + limit, total_items) if limit else total_items
                items_to_process = queue_list[offset:end_idx]
                
                result = []
                for position, item in enumerate(items_to_process, start=offset):
                    if (hasattr(item, 'item') and isinstance(item.item, dict) and 
                        'uuid' in item.item):
                        result.append({
                            'uuid': item.item['uuid'],
                            'position': position,
                            'priority': item.priority
                        })
                
                return {
                    'items': result,
                    'total_items': total_items,
                    'returned_items': len(result),
                    'has_more': (offset + len(result)) < total_items
                }
                
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get all queued UUIDs: {str(e)}")
            return {'items': [], 'total_items': 0, 'returned_items': 0, 'has_more': False}
    
    def get_queue_summary(self) -> Dict[str, Any]:
        """Get queue summary statistics"""
        try:
            with self._lock:
                queue_list = list(self._priority_items)
                total_items = len(queue_list)
                
                if total_items == 0:
                    return {
                        'total_items': 0, 'priority_breakdown': {},
                        'immediate_items': 0, 'clone_items': 0, 'scheduled_items': 0
                    }
                
                immediate_items = clone_items = scheduled_items = 0
                priority_counts = {}
                
                for item in queue_list:
                    priority = item.priority
                    priority_counts[priority] = priority_counts.get(priority, 0) + 1
                    
                    if priority == 1:
                        immediate_items += 1
                    elif priority == 5:
                        clone_items += 1
                    elif priority > 100:
                        scheduled_items += 1
                
                return {
                    'total_items': total_items,
                    'priority_breakdown': priority_counts,
                    'immediate_items': immediate_items,
                    'clone_items': clone_items,
                    'scheduled_items': scheduled_items,
                    'min_priority': min(priority_counts.keys()) if priority_counts else None,
                    'max_priority': max(priority_counts.keys()) if priority_counts else None
                }
                
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get queue summary: {str(e)}")
            return {'total_items': 0, 'priority_breakdown': {}, 'immediate_items': 0, 
                   'clone_items': 0, 'scheduled_items': 0}
    
    # PRIVATE METHODS
    def _get_item_uuid(self, item) -> str:
        """Safely extract UUID from item for logging"""
        try:
            if hasattr(item, 'item') and isinstance(item.item, dict):
                return item.item.get('uuid', 'unknown')
        except Exception:
            pass
        return 'unknown'

    def _emit_put_signals(self, item):
        """Emit signals when item is added"""
        try:
            # Watch update signal
            if hasattr(item, 'item') and isinstance(item.item, dict) and 'uuid' in item.item:
                watch_check_update = signal('watch_check_update')
                if watch_check_update:
                    watch_check_update.send(watch_uuid=item.item['uuid'])

            # Queue length signal
            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to emit put signals: {str(e)}")

    def _emit_get_signals(self):
        """Emit signals when item is removed"""
        try:
            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to emit get signals: {str(e)}")


class NotificationQueue:
    """
    Ultra-reliable notification queue using pure janus.
    
    CRITICAL DESIGN NOTE: Both sync_q and async_q are required because:
    - sync_q: Used by Flask routes, ticker threads, and other synchronous code
    - async_q: Used by async workers and coroutines
    
    DO NOT REMOVE EITHER INTERFACE - they bridge different execution contexts.
    See RecheckPriorityQueue docstring above for detailed explanation.
    
    Simple wrapper around janus with bulletproof error handling.
    """
    
    def __init__(self, maxsize: int = 0, datastore=None):
        try:
            # Use pure threading.Queue to avoid event loop binding issues
            self._notification_queue = queue.Queue(maxsize=maxsize if maxsize > 0 else 0)
            self.notification_event_signal = signal('notification_event')
            self.datastore = datastore  # For checking all_muted setting
            self._lock = threading.RLock()
            logger.debug("NotificationQueue initialized successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to initialize NotificationQueue: {str(e)}")
            raise

    def set_datastore(self, datastore):
        """Set datastore reference after initialization (for circular dependency handling)"""
        self.datastore = datastore
    
    def put(self, item: Dict[str, Any], block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync put with signal emission"""
        logger.trace(f"NotificationQueue.put() called for item: {item.get('uuid', 'unknown')}, block={block}, timeout={timeout}")
        try:
            # Check if all notifications are muted
            if self.datastore and self.datastore.data['settings']['application'].get('all_muted', False):
                logger.debug(f"Notification blocked - all notifications are muted: {item.get('uuid', 'unknown')}")
                return False

            with self._lock:
                self._notification_queue.put(item, block=block, timeout=timeout)
            self._emit_notification_signal(item)
            logger.trace(f"NotificationQueue.put() successfully queued notification: {item.get('uuid', 'unknown')}")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to put notification {item.get('uuid', 'unknown')}: {str(e)}")
            return False
    
    async def async_put(self, item: Dict[str, Any], executor=None):
        """Async put with signal emission - uses thread pool

        Args:
            item: Notification item to queue
            executor: Optional ThreadPoolExecutor
        """
        logger.trace(f"NotificationQueue.async_put() called for item: {item.get('uuid', 'unknown')}, executor={executor}")
        import asyncio
        try:
            # Check if all notifications are muted
            if self.datastore and self.datastore.data['settings']['application'].get('all_muted', False):
                logger.debug(f"Notification blocked - all notifications are muted: {item.get('uuid', 'unknown')}")
                return False

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, lambda: self.put(item, block=True, timeout=5.0))
            logger.trace(f"NotificationQueue.async_put() successfully queued notification: {item.get('uuid', 'unknown')}")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put notification {item.get('uuid', 'unknown')}: {str(e)}")
            return False

    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get"""
        logger.trace(f"NotificationQueue.get() called, block={block}, timeout={timeout}")
        try:
            with self._lock:
                item = self._notification_queue.get(block=block, timeout=timeout)
            logger.trace(f"NotificationQueue.get() retrieved item: {item.get('uuid', 'unknown') if isinstance(item, dict) else 'unknown'}")
            return item
        except queue.Empty as e:
            logger.trace(f"NotificationQueue.get() timed out - queue is empty (timeout={timeout})")
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get notification: {type(e).__name__}: {str(e)}")
            raise e

    async def async_get(self, executor=None):
        """Async get - uses thread pool

        Args:
            executor: Optional ThreadPoolExecutor
        """
        logger.trace(f"NotificationQueue.async_get() called, executor={executor}")
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(executor, lambda: self.get(block=True, timeout=1.0))
            logger.trace(f"NotificationQueue.async_get() retrieved item: {item.get('uuid', 'unknown') if isinstance(item, dict) else 'unknown'}")
            return item
        except queue.Empty as e:
            logger.trace(f"NotificationQueue.async_get() timed out - queue is empty")
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async get notification: {type(e).__name__}: {str(e)}")
            raise e
    
    def qsize(self) -> int:
        """Get current queue size"""
        try:
            with self._lock:
                return self._notification_queue.qsize()
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get notification queue size: {str(e)}")
            return 0

    def empty(self) -> bool:
        """Check if queue is empty"""
        return self.qsize() == 0

    def close(self):
        """Close the queue"""
        try:
            # Nothing to close for threading.Queue
            logger.debug("NotificationQueue closed successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to close NotificationQueue: {str(e)}")
    
    def _emit_notification_signal(self, item: Dict[str, Any]):
        """Emit notification signal"""
        try:
            if self.notification_event_signal and isinstance(item, dict):
                watch_uuid = item.get('uuid')
                if watch_uuid:
                    self.notification_event_signal.send(watch_uuid=watch_uuid)
                else:
                    self.notification_event_signal.send()
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to emit notification signal: {str(e)}")