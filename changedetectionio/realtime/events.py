from flask_socketio import emit
from loguru import logger
from blinker import signal


def register_watch_operation_handlers(socketio, datastore):
    """Register Socket.IO event handlers for watch operations"""
    
    @socketio.on('watch_operation')
    def handle_watch_operation(data):
        """Handle watch operations like pause, mute, recheck via Socket.IO"""
        try:
            op = data.get('op')
            uuid = data.get('uuid')
            
            logger.debug(f"Socket.IO: Received watch operation '{op}' for UUID {uuid}")
            
            if not op or not uuid:
                emit('operation_result', {'success': False, 'error': 'Missing operation or UUID'})
                return
            
            # Check if watch exists
            if not datastore.data['watching'].get(uuid):
                emit('operation_result', {'success': False, 'error': 'Watch not found'})
                return
            
            watch = datastore.data['watching'][uuid]
            
            # Perform the operation
            if op == 'pause':
                watch.toggle_pause()
                logger.info(f"Socket.IO: Toggled pause for watch {uuid}")
            elif op == 'mute':
                watch.toggle_mute()
                logger.info(f"Socket.IO: Toggled mute for watch {uuid}")
            elif op == 'recheck':
                # Import here to avoid circular imports
                from changedetectionio.flask_app import update_q
                from changedetectionio import queuedWatchMetaData
                from changedetectionio import worker_handler
                
                worker_handler.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
                logger.info(f"Socket.IO: Queued recheck for watch {uuid}")
            else:
                emit('operation_result', {'success': False, 'error': f'Unknown operation: {op}'})
                return
            
            # Send signal to update UI
            watch_check_update = signal('watch_check_update')
            if watch_check_update:
                watch_check_update.send(watch_uuid=uuid)
            
            # Send success response to client
            emit('operation_result', {'success': True, 'operation': op, 'uuid': uuid})
            
        except Exception as e:
            logger.error(f"Socket.IO error in handle_watch_operation: {str(e)}")
            emit('operation_result', {'success': False, 'error': str(e)})
