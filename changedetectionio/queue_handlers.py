from blinker import signal
from loguru import logger
from typing import Dict, List, Any, Optional
import heapq
import queue
import threading

try:
    import janus
except ImportError:
    logger.critical(f"CRITICAL: janus library is required. Install with: pip install janus")
    raise


class RecheckPriorityQueue:
    """
    Ultra-reliable priority queue using janus for async/sync bridging.
    
    CRITICAL DESIGN NOTE: Both sync_q and async_q are required because:
    - sync_q: Used by Flask routes, ticker threads, and other synchronous code
    - async_q: Used by async workers (the actual fetchers/processors) and coroutines
    
    DO NOT REMOVE EITHER INTERFACE - they bridge different execution contexts:
    - Synchronous code (Flask, threads) cannot use async methods without blocking
    - Async code cannot use sync methods without blocking the event loop
    - janus provides the only safe bridge between these two worlds
    
    Attempting to unify to async-only would require:
    - Converting all Flask routes to async (major breaking change)
    - Using asyncio.run() in sync contexts (causes deadlocks)
    - Thread-pool wrapping (adds complexity and overhead)
    
    Minimal implementation focused on reliability:
    - Pure janus for sync/async bridge
    - Thread-safe priority ordering  
    - Bulletproof error handling with critical logging
    """
    
    def __init__(self, maxsize: int = 0):
        try:
            self._janus_queue = janus.Queue(maxsize=maxsize)
            # BOTH interfaces required - see class docstring for why
            self.sync_q = self._janus_queue.sync_q   # Flask routes, ticker thread
            self.async_q = self._janus_queue.async_q # Async workers
            
            # Priority storage - thread-safe
            self._priority_items = []
            self._lock = threading.RLock()
            
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
            # Add to priority storage
            with self._lock:
                heapq.heappush(self._priority_items, item)
            
            # Notify via janus sync queue
            self.sync_q.put(True, block=block, timeout=timeout)
            
            # Emit signals
            self._emit_put_signals(item)
            
            logger.debug(f"Successfully queued item: {self._get_item_uuid(item)}")
            return True
            
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to put item {self._get_item_uuid(item)}: {str(e)}")
            # Remove from priority storage if janus put failed
            try:
                with self._lock:
                    if item in self._priority_items:
                        self._priority_items.remove(item)
                        heapq.heapify(self._priority_items)
            except Exception as cleanup_e:
                logger.critical(f"CRITICAL: Failed to cleanup after put failure: {str(e)}")
            return False
    
    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get with priority ordering"""
        try:
            # Wait for notification
            self.sync_q.get(block=block, timeout=timeout)

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

        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get item from queue: {str(e)}")
            raise
    
    # ASYNC INTERFACE (for workers)
    async def async_put(self, item):
        """Pure async put with priority ordering"""
        try:
            # Add to priority storage
            with self._lock:
                heapq.heappush(self._priority_items, item)
            
            # Notify via janus async queue
            await self.async_q.put(True)
            
            # Emit signals
            self._emit_put_signals(item)
            
            logger.debug(f"Successfully async queued item: {self._get_item_uuid(item)}")
            return True
            
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put item {self._get_item_uuid(item)}: {str(e)}")
            # Remove from priority storage if janus put failed
            try:
                with self._lock:
                    if item in self._priority_items:
                        self._priority_items.remove(item)
                        heapq.heapify(self._priority_items)
            except Exception as cleanup_e:
                logger.critical(f"CRITICAL: Failed to cleanup after async put failure: {str(e)}")
            return False
    
    async def async_get(self):
        """Pure async get with priority ordering"""
        try:
            # Wait for notification
            await self.async_q.get()

            # Get highest priority item
            with self._lock:
                if not self._priority_items:
                    logger.critical(f"CRITICAL: Async queue notification received but no priority items available")
                    raise Exception("Priority queue inconsistency")
                item = heapq.heappop(self._priority_items)

            # Emit signals
            self._emit_get_signals()

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
    
    def close(self):
        """Close the janus queue"""
        try:
            self._janus_queue.close()
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
    
    def __init__(self, maxsize: int = 0):
        try:
            self._janus_queue = janus.Queue(maxsize=maxsize)
            # BOTH interfaces required - see class docstring for why
            self.sync_q = self._janus_queue.sync_q   # Flask routes, threads
            self.async_q = self._janus_queue.async_q # Async workers
            self.notification_event_signal = signal('notification_event')
            logger.debug("NotificationQueue initialized successfully")
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to initialize NotificationQueue: {str(e)}")
            raise
    
    def put(self, item: Dict[str, Any], block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync put with signal emission"""
        try:
            self.sync_q.put(item, block=block, timeout=timeout)
            self._emit_notification_signal(item)
            logger.debug(f"Successfully queued notification: {item.get('uuid', 'unknown')}")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to put notification {item.get('uuid', 'unknown')}: {str(e)}")
            return False
    
    async def async_put(self, item: Dict[str, Any]):
        """Pure async put with signal emission"""
        try:
            await self.async_q.put(item)
            self._emit_notification_signal(item)
            logger.debug(f"Successfully async queued notification: {item.get('uuid', 'unknown')}")
            return True
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async put notification {item.get('uuid', 'unknown')}: {str(e)}")
            return False
    
    def get(self, block: bool = True, timeout: Optional[float] = None):
        """Thread-safe sync get"""
        try:
            return self.sync_q.get(block=block, timeout=timeout)
        except queue.Empty as e:
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get notification: {str(e)}")
            raise e
    
    async def async_get(self):
        """Pure async get"""
        try:
            return await self.async_q.get()
        except queue.Empty as e:
            raise e
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to async get notification: {str(e)}")
            raise e
    
    def qsize(self) -> int:
        """Get current queue size"""
        try:
            return self.sync_q.qsize()
        except Exception as e:
            logger.critical(f"CRITICAL: Failed to get notification queue size: {str(e)}")
            return 0
    
    def empty(self) -> bool:
        """Check if queue is empty"""
        return self.qsize() == 0
    
    def close(self):
        """Close the janus queue"""
        try:
            self._janus_queue.close()
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