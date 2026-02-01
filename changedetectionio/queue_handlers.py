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
    - One shared queue accessed safely via threading primitives
    - Workers use run_in_executor to access queue without blocking their event loop

    IMPLEMENTATION:
    - Pure threading.Queue for notifications (no event loop binding)
    - Heapq-based priority storage (thread-safe with RLock)
    - Async methods wrap sync methods via run_in_executor
    - Supports both sync and async access patterns

    WHY NOT JANUS:
    - Janus binds to ONE event loop at creation time
    - Our architecture has 15+ workers, each with separate event loops
    - Workers in different threads/loops cannot share janus async interface
    - Pure threading approach works across all event loops
    """
    
    def __init__(self, maxsize: int = 0):
        try:
            # Use pure threading.Queue for notification - no janus needed
            # This avoids event loop binding issues with multiple worker threads
            import asyncio
            self._notification_queue = queue.Queue(maxsize=maxsize if maxsize > 0 else 0)

            # Priority storage - thread-safe
            self._priority_items = []
            self._lock = threading.RLock()

            # Condition variable for async wait support
            self._condition = threading.Condition(self._lock)

            # Signals for UI updates
            self.queue_length_signal = signal('queue_length')

            logger.debug("RecheckPriorityQueue initialized successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to initialize RecheckPriorityQueue: {str(e)}")
            raise
    
    # SYNC INTERFACE (for ticker thread)
    def put(self, item, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync put with priority ordering"""
        try:
            # Add to priority storage and notify waiters
            with self._condition:
                heapq.heappush(self._priority_items, item)
                self._notification_queue.put(True, block=False)  # Notification only
                self._condition.notify_all()  # Wake up any async waiters

            # Emit signals
            self._emit_put_signals(item)

            logger.trace(f"Successfully queued item: {self._get_item_uuid(item)}")
            return True

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to put item {self._get_item_uuid(item)}: {str(e)}")
            # Remove from priority storage if put failed
            try:
                with self._condition:
                    if item in self._priority_items:
                        self._priority_items.remove(item)
                        heapq.heapify(self._priority_items)
            except Exception as cleanup_e:
                logger.critical(f"CRITICAL: Failed to cleanup after put failure: {str(e)}")
            return False
    
    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get with priority ordering"""
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

            # Emit signals
            self._emit_get_signals()

            logger.debug(f"Successfully retrieved item: {self._get_item_uuid(item)}")
            return item

        except queue_module.Empty:
            # Queue is empty with timeout - expected behavior, re-raise without logging
            raise
        except Exception as e:
            # Re-raise without logging - caller (worker) will handle and log appropriately
            raise
    
    # ASYNC INTERFACE (for workers)
    async def async_put(self, item, executor=None):
        """Async put with priority ordering - uses thread pool to avoid blocking

        Args:
            item: Item to add to queue
            executor: Optional ThreadPoolExecutor. If None, uses default pool.
        """
        import asyncio
        try:
            # Use run_in_executor to call sync put without blocking event loop
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                executor,  # Use provided executor or default
                lambda: self.put(item, block=True, timeout=5.0)
            )

            logger.debug(f"Successfully async queued item: {self._get_item_uuid(item)}")
            return result

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put item {self._get_item_uuid(item)}: {str(e)}")
            return False
    
    async def async_get(self, executor=None):
        """Async get with priority ordering - uses thread pool to avoid blocking

        Args:
            executor: Optional ThreadPoolExecutor. If None, uses default pool.
                     With many workers (30+), pass custom executor scaled to worker count.
        """
        import asyncio
        try:
            # Use run_in_executor to call sync get without blocking event loop
            # This works across multiple event loops since it uses threading
            loop = asyncio.get_event_loop()
            item = await loop.run_in_executor(
                executor,  # Use provided executor (scales with FETCH_WORKERS) or default
                lambda: self.get(block=True, timeout=1.0)
            )

            logger.debug(f"Successfully async retrieved item: {self._get_item_uuid(item)}")
            return item

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async get item from queue: {str(e)}")
            raise
    
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
        try:
            # Check if all notifications are muted
            if self.datastore and self.datastore.data['settings']['application'].get('all_muted', False):
                logger.debug(f"Notification blocked - all notifications are muted: {item.get('uuid', 'unknown')}")
                return False

            with self._lock:
                self._notification_queue.put(item, block=block, timeout=timeout)
            self._emit_notification_signal(item)
            logger.debug(f"Successfully queued notification: {item.get('uuid', 'unknown')}")
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
        import asyncio
        try:
            # Check if all notifications are muted
            if self.datastore and self.datastore.data['settings']['application'].get('all_muted', False):
                logger.debug(f"Notification blocked - all notifications are muted: {item.get('uuid', 'unknown')}")
                return False

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(executor, lambda: self.put(item, block=True, timeout=5.0))
            logger.debug(f"Successfully async queued notification: {item.get('uuid', 'unknown')}")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put notification {item.get('uuid', 'unknown')}: {str(e)}")
            return False

    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get"""
        try:
            with self._lock:
                return self._notification_queue.get(block=block, timeout=timeout)
        except queue.Empty as e:
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get notification: {str(e)}")
            raise e

    async def async_get(self, executor=None):
        """Async get - uses thread pool

        Args:
            executor: Optional ThreadPoolExecutor
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(executor, lambda: self.get(block=True, timeout=1.0))
        except queue.Empty as e:
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async get notification: {str(e)}")
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