import queue
import asyncio
from blinker import signal
from loguru import logger


class NotificationQueue(queue.Queue):
    """
    Extended Queue that sends a 'notification_event' signal when notifications are added.
    
    This class extends the standard Queue and adds a signal emission after a notification
    is put into the queue. The signal includes the watch UUID if available.
    """
    
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        try:
            self.notification_event_signal = signal('notification_event')
        except Exception as e:
            logger.critical(f"Exception creating notification_event signal: {e}")

    def put(self, item, block=True, timeout=None):
        # Call the parent's put method first
        super().put(item, block, timeout)
        
        # After putting the notification in the queue, emit signal with watch UUID
        try:
            if self.notification_event_signal and isinstance(item, dict):
                watch_uuid = item.get('uuid')
                if watch_uuid:
                    # Send the notification_event signal with the watch UUID
                    self.notification_event_signal.send(watch_uuid=watch_uuid)
                    logger.trace(f"NotificationQueue: Emitted notification_event signal for watch UUID {watch_uuid}")
                else:
                    # Send signal without UUID for system notifications
                    self.notification_event_signal.send()
                    logger.trace("NotificationQueue: Emitted notification_event signal for system notification")
        except Exception as e:
            logger.error(f"Exception emitting notification_event signal: {e}")

class SignalPriorityQueue(queue.PriorityQueue):
    """
    Extended PriorityQueue that sends a signal when items with a UUID are added.
    
    This class extends the standard PriorityQueue and adds a signal emission
    after an item is put into the queue. If the item contains a UUID, the signal
    is sent with that UUID as a parameter.
    """
    
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        try:
            self.queue_length_signal = signal('queue_length')
        except Exception as e:
            logger.critical(f"Exception: {e}")

    def put(self, item, block=True, timeout=None):
        # Call the parent's put method first
        super().put(item, block, timeout)
        
        # After putting the item in the queue, check if it has a UUID and emit signal
        if hasattr(item, 'item') and isinstance(item.item, dict) and 'uuid' in item.item:
            uuid = item.item['uuid']
            # Get the signal and send it if it exists
            watch_check_update = signal('watch_check_update')
            if watch_check_update:
                # Send the watch_uuid parameter
                watch_check_update.send(watch_uuid=uuid)
        
        # Send queue_length signal with current queue size
        try:

            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())
        except Exception as e:
            logger.critical(f"Exception: {e}")

    def get(self, block=True, timeout=None):
        # Call the parent's get method first
        item = super().get(block, timeout)
        
        # Send queue_length signal with current queue size
        try:
            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())
        except Exception as e:
            logger.critical(f"Exception: {e}")
        return item
    
    def get_uuid_position(self, target_uuid):
        """
        Find the position of a watch UUID in the priority queue.
        Optimized for large queues - O(n) complexity instead of O(n log n).
        
        Args:
            target_uuid: The UUID to search for
            
        Returns:
            dict: Contains position info or None if not found
                - position: 0-based position in queue (0 = next to be processed)
                - total_items: total number of items in queue
                - priority: the priority value of the found item
        """
        with self.mutex:
            queue_list = list(self.queue)
            total_items = len(queue_list)
            
            if total_items == 0:
                return {
                    'position': None,
                    'total_items': 0,
                    'priority': None,
                    'found': False
                }
            
            # Find the target item and its priority first - O(n)
            target_item = None
            target_priority = None
            
            for item in queue_list:
                if (hasattr(item, 'item') and 
                    isinstance(item.item, dict) and 
                    item.item.get('uuid') == target_uuid):
                    target_item = item
                    target_priority = item.priority
                    break
            
            if target_item is None:
                return {
                    'position': None,
                    'total_items': total_items,
                    'priority': None,
                    'found': False
                }
            
            # Count how many items have higher priority (lower numbers) - O(n)
            position = 0
            for item in queue_list:
                # Items with lower priority numbers are processed first
                if item.priority < target_priority:
                    position += 1
                elif item.priority == target_priority and item != target_item:
                    # For same priority, count items that come before this one
                    # (Note: this is approximate since heap order isn't guaranteed for equal priorities)
                    position += 1
            
            return {
                'position': position,
                'total_items': total_items,
                'priority': target_priority,
                'found': True
            }
    
    def get_all_queued_uuids(self, limit=None, offset=0):
        """
        Get UUIDs currently in the queue with their positions.
        For large queues, use limit/offset for pagination.
        
        Args:
            limit: Maximum number of items to return (None = all)
            offset: Number of items to skip (for pagination)
        
        Returns:
            dict: Contains items and metadata
                - items: List of dicts with uuid, position, and priority
                - total_items: Total number of items in queue
                - returned_items: Number of items returned
                - has_more: Whether there are more items after this page
        """
        with self.mutex:
            queue_list = list(self.queue)
            total_items = len(queue_list)
            
            if total_items == 0:
                return {
                    'items': [],
                    'total_items': 0,
                    'returned_items': 0,
                    'has_more': False
                }
            
            # For very large queues, warn about performance
            if total_items > 1000 and limit is None:
                logger.warning(f"Getting all {total_items} queued items without limit - this may be slow")
            
            # Sort only if we need exact positions (expensive for large queues)
            if limit is not None and limit <= 100:
                # For small requests, we can afford to sort
                queue_items = sorted(queue_list)
                end_idx = min(offset + limit, len(queue_items)) if limit else len(queue_items)
                items_to_process = queue_items[offset:end_idx]
                
                result = []
                for position, item in enumerate(items_to_process, start=offset):
                    if (hasattr(item, 'item') and 
                        isinstance(item.item, dict) and 
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
            else:
                # For large requests, return items with approximate positions
                # This is much faster O(n) instead of O(n log n)
                result = []
                processed = 0
                skipped = 0
                
                for item in queue_list:
                    if (hasattr(item, 'item') and 
                        isinstance(item.item, dict) and 
                        'uuid' in item.item):
                        
                        if skipped < offset:
                            skipped += 1
                            continue
                        
                        if limit and processed >= limit:
                            break
                        
                        # Approximate position based on priority comparison
                        approx_position = sum(1 for other in queue_list if other.priority < item.priority)
                        
                        result.append({
                            'uuid': item.item['uuid'],
                            'position': approx_position,  # Approximate
                            'priority': item.priority
                        })
                        processed += 1
                
                return {
                    'items': result,
                    'total_items': total_items,
                    'returned_items': len(result),
                    'has_more': (offset + len(result)) < total_items,
                    'note': 'Positions are approximate for performance with large queues'
                }
    
    def get_queue_summary(self):
        """
        Get a quick summary of queue state without expensive operations.
        O(n) complexity - fast even for large queues.
        
        Returns:
            dict: Queue summary statistics
        """
        with self.mutex:
            queue_list = list(self.queue)
            total_items = len(queue_list)
            
            if total_items == 0:
                return {
                    'total_items': 0,
                    'priority_breakdown': {},
                    'immediate_items': 0,
                    'clone_items': 0,
                    'scheduled_items': 0
                }
            
            # Count items by priority type - O(n)
            immediate_items = 0  # priority 1
            clone_items = 0      # priority 5  
            scheduled_items = 0  # priority > 100 (timestamps)
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


class AsyncSignalPriorityQueue(asyncio.PriorityQueue):
    """
    Async version of SignalPriorityQueue that sends signals when items are added/removed.
    
    This class extends asyncio.PriorityQueue and maintains the same signal behavior
    as the synchronous version for real-time UI updates.
    """
    
    def __init__(self, maxsize=0):
        super().__init__(maxsize)
        try:
            self.queue_length_signal = signal('queue_length')
        except Exception as e:
            logger.critical(f"Exception: {e}")

    async def put(self, item):
        # Call the parent's put method first
        await super().put(item)
        
        # After putting the item in the queue, check if it has a UUID and emit signal
        if hasattr(item, 'item') and isinstance(item.item, dict) and 'uuid' in item.item:
            uuid = item.item['uuid']
            # Get the signal and send it if it exists
            watch_check_update = signal('watch_check_update')
            if watch_check_update:
                # Send the watch_uuid parameter
                watch_check_update.send(watch_uuid=uuid)
        
        # Send queue_length signal with current queue size
        try:
            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())
        except Exception as e:
            logger.critical(f"Exception: {e}")

    async def get(self):
        # Call the parent's get method first
        item = await super().get()
        
        # Send queue_length signal with current queue size
        try:
            if self.queue_length_signal:
                self.queue_length_signal.send(length=self.qsize())
        except Exception as e:
            logger.critical(f"Exception: {e}")
        return item
    
    @property
    def queue(self):
        """
        Provide compatibility with sync PriorityQueue.queue access
        Returns the internal queue for template access
        """
        return self._queue if hasattr(self, '_queue') else []
    
    def get_uuid_position(self, target_uuid):
        """
        Find the position of a watch UUID in the async priority queue.
        Optimized for large queues - O(n) complexity instead of O(n log n).
        
        Args:
            target_uuid: The UUID to search for
            
        Returns:
            dict: Contains position info or None if not found
                - position: 0-based position in queue (0 = next to be processed)
                - total_items: total number of items in queue
                - priority: the priority value of the found item
        """
        queue_list = list(self._queue)
        total_items = len(queue_list)
        
        if total_items == 0:
            return {
                'position': None,
                'total_items': 0,
                'priority': None,
                'found': False
            }
        
        # Find the target item and its priority first - O(n)
        target_item = None
        target_priority = None
        
        for item in queue_list:
            if (hasattr(item, 'item') and 
                isinstance(item.item, dict) and 
                item.item.get('uuid') == target_uuid):
                target_item = item
                target_priority = item.priority
                break
        
        if target_item is None:
            return {
                'position': None,
                'total_items': total_items,
                'priority': None,
                'found': False
            }
        
        # Count how many items have higher priority (lower numbers) - O(n)
        position = 0
        for item in queue_list:
            if item.priority < target_priority:
                position += 1
            elif item.priority == target_priority and item != target_item:
                position += 1
        
        return {
            'position': position,
            'total_items': total_items,
            'priority': target_priority,
            'found': True
        }
    
    def get_all_queued_uuids(self, limit=None, offset=0):
        """
        Get UUIDs currently in the async queue with their positions.
        For large queues, use limit/offset for pagination.
        
        Args:
            limit: Maximum number of items to return (None = all)
            offset: Number of items to skip (for pagination)
        
        Returns:
            dict: Contains items and metadata (same structure as sync version)
        """
        queue_list = list(self._queue)
        total_items = len(queue_list)
        
        if total_items == 0:
            return {
                'items': [],
                'total_items': 0,
                'returned_items': 0,
                'has_more': False
            }
        
        # Same logic as sync version but without mutex
        if limit is not None and limit <= 100:
            queue_items = sorted(queue_list)
            end_idx = min(offset + limit, len(queue_items)) if limit else len(queue_items)
            items_to_process = queue_items[offset:end_idx]
            
            result = []
            for position, item in enumerate(items_to_process, start=offset):
                if (hasattr(item, 'item') and 
                    isinstance(item.item, dict) and 
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
        else:
            # Fast approximate positions for large queues
            result = []
            processed = 0
            skipped = 0
            
            for item in queue_list:
                if (hasattr(item, 'item') and 
                    isinstance(item.item, dict) and 
                    'uuid' in item.item):
                    
                    if skipped < offset:
                        skipped += 1
                        continue
                    
                    if limit and processed >= limit:
                        break
                    
                    approx_position = sum(1 for other in queue_list if other.priority < item.priority)
                    
                    result.append({
                        'uuid': item.item['uuid'],
                        'position': approx_position,
                        'priority': item.priority
                    })
                    processed += 1
            
            return {
                'items': result,
                'total_items': total_items,
                'returned_items': len(result),
                'has_more': (offset + len(result)) < total_items,
                'note': 'Positions are approximate for performance with large queues'
            }
    
    def get_queue_summary(self):
        """
        Get a quick summary of async queue state.
        O(n) complexity - fast even for large queues.
        """
        queue_list = list(self._queue)
        total_items = len(queue_list)
        
        if total_items == 0:
            return {
                'total_items': 0,
                'priority_breakdown': {},
                'immediate_items': 0,
                'clone_items': 0,
                'scheduled_items': 0
            }
        
        immediate_items = 0
        clone_items = 0
        scheduled_items = 0
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
