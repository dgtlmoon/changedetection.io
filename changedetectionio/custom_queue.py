import queue
from blinker import signal
from loguru import logger

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
