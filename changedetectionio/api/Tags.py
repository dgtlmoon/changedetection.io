from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_pool
from flask_expects_json import expects_json
from flask_restful import abort, Resource
from loguru import logger

import threading
from flask import request
from . import auth

# Import schemas from __init__.py
from . import schema_tag, schema_create_tag, schema_update_tag, validate_openapi_request


class Tag(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single tag
    # curl http://localhost:5000/api/v1/tag/<string:uuid>
    @auth.check_token
    @validate_openapi_request('getTag')
    def get(self, uuid):
        """Get data for a single tag/group, toggle notification muting, or recheck all."""
        tag = self.datastore.data['settings']['application']['tags'].get(uuid)
        if not tag:
            abort(404, message=f'No tag exists with the UUID of {uuid}')

        if request.args.get('recheck'):
            # Recheck all watches with this tag, including muted
            # First collect watches to queue
            watches_to_queue = []
            for k in sorted(self.datastore.data['watching'].items(), key=lambda item: item[1].get('last_checked', 0)):
                watch_uuid = k[0]
                watch = k[1]
                if not watch['paused'] and tag['uuid'] in watch['tags']:
                    watches_to_queue.append(watch_uuid)

            # If less than 20 watches, queue synchronously for immediate feedback
            if len(watches_to_queue) < 20:
                for watch_uuid in watches_to_queue:
                    worker_pool.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                return {'status': f'OK, queued {len(watches_to_queue)} watches for rechecking'}, 200
            else:
                # 20+ watches - queue in background thread to avoid blocking API response
                def queue_watches_background():
                    """Background thread to queue watches - discarded after completion."""
                    try:
                        for watch_uuid in watches_to_queue:
                            worker_pool.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                        logger.info(f"Background queueing complete for tag {tag['uuid']}: {len(watches_to_queue)} watches queued")
                    except Exception as e:
                        logger.error(f"Error in background queueing for tag {tag['uuid']}: {e}")

                # Start background thread and return immediately
                thread = threading.Thread(target=queue_watches_background, daemon=True, name=f"QueueTag-{tag['uuid'][:8]}")
                thread.start()

                return {'status': f'OK, queueing {len(watches_to_queue)} watches in background'}, 202

        if request.args.get('muted', '') == 'muted':
            tag['notification_muted'] = True
            tag.commit()
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            tag['notification_muted'] = False
            tag.commit()
            return "OK", 200

        return tag

    @auth.check_token
    @validate_openapi_request('deleteTag')
    def delete(self, uuid):
        """Delete a tag/group and remove it from all watches."""
        if not self.datastore.data['settings']['application']['tags'].get(uuid):
            abort(400, message='No tag exists with the UUID of {}'.format(uuid))

        # Delete the tag, and any tag reference
        del self.datastore.data['settings']['application']['tags'][uuid]

        # Delete tag.json file if it exists
        import os
        tag_dir = os.path.join(self.datastore.datastore_path, uuid)
        tag_json = os.path.join(tag_dir, "tag.json")
        if os.path.exists(tag_json):
            try:
                os.unlink(tag_json)
                logger.info(f"Deleted tag.json for tag {uuid}")
            except Exception as e:
                logger.error(f"Failed to delete tag.json for tag {uuid}: {e}")

        # Remove tag from all watches
        for watch_uuid, watch in self.datastore.data['watching'].items():
            if watch.get('tags') and uuid in watch['tags']:
                watch['tags'].remove(uuid)
                watch.commit()

        return 'OK', 204

    @auth.check_token
    @validate_openapi_request('updateTag')
    @expects_json(schema_update_tag)
    def put(self, uuid):
        """Update tag information."""
        tag = self.datastore.data['settings']['application']['tags'].get(uuid)
        if not tag:
            abort(404, message='No tag exists with the UUID of {}'.format(uuid))

        # Validate restock_settings if provided
        if 'restock_settings' in request.json:
            restock_settings = request.json.get('restock_settings', {})
            
            # Validate in_stock_processing values
            if 'in_stock_processing' in restock_settings:
                valid_processing_modes = ['in_stock_only', 'all_changes', 'off']
                if restock_settings['in_stock_processing'] not in valid_processing_modes:
                    return f"Invalid in_stock_processing value. Must be one of: {valid_processing_modes}", 400
            
            # Validate price thresholds are numbers if provided
            for price_field in ['price_change_min', 'price_change_max']:
                if price_field in restock_settings and restock_settings[price_field] is not None:
                    try:
                        float(restock_settings[price_field])
                    except (ValueError, TypeError):
                        return f"Invalid {price_field} value. Must be a number or null.", 400
            
            # Validate price_change_threshold_percent
            if 'price_change_threshold_percent' in restock_settings and restock_settings['price_change_threshold_percent'] is not None:
                try:
                    threshold = float(restock_settings['price_change_threshold_percent'])
                    if threshold < 0 or threshold > 100:
                        return "price_change_threshold_percent must be between 0 and 100", 400
                except (ValueError, TypeError):
                    return "Invalid price_change_threshold_percent value. Must be a number between 0 and 100 or null.", 400

        tag.update(request.json)
        tag.commit()

        return "OK", 200


    @auth.check_token
    @validate_openapi_request('createTag')
    def post(self):
        """Create a single tag/group."""
        json_data = request.get_json()
        title = json_data.get("title",'').strip()

        # Validate required title field
        if not title:
            return "Title is required", 400

        # Validate restock_settings if provided
        if 'restock_settings' in json_data:
            restock_settings = json_data.get('restock_settings', {})
            
            # Validate in_stock_processing values
            if 'in_stock_processing' in restock_settings:
                valid_processing_modes = ['in_stock_only', 'all_changes', 'off']
                if restock_settings['in_stock_processing'] not in valid_processing_modes:
                    return f"Invalid in_stock_processing value. Must be one of: {valid_processing_modes}", 400
            
            # Validate price thresholds are numbers if provided
            for price_field in ['price_change_min', 'price_change_max']:
                if price_field in restock_settings and restock_settings[price_field] is not None:
                    try:
                        float(restock_settings[price_field])
                    except (ValueError, TypeError):
                        return f"Invalid {price_field} value. Must be a number or null.", 400
            
            # Validate price_change_threshold_percent
            if 'price_change_threshold_percent' in restock_settings and restock_settings['price_change_threshold_percent'] is not None:
                try:
                    threshold = float(restock_settings['price_change_threshold_percent'])
                    if threshold < 0 or threshold > 100:
                        return "price_change_threshold_percent must be between 0 and 100", 400
                except (ValueError, TypeError):
                    return "Invalid price_change_threshold_percent value. Must be a number between 0 and 100 or null.", 400

        # Create the new tag with basic properties
        new_uuid = self.datastore.add_tag(title=title)
        if new_uuid:
            # If additional properties were provided, update the tag with them
            tag = self.datastore.data['settings']['application']['tags'][new_uuid]
            
            # Update with all provided properties (excluding title which was already set)
            update_data = {k: v for k, v in json_data.items() if k != 'title'}
            if update_data:
                tag.update(update_data)
                self.datastore.needs_write_urgent = True
                
            return {'uuid': new_uuid}, 201
        else:
            return "Invalid or unsupported tag", 400

class Tags(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('listTags')
    def get(self):
        """List tags/groups."""
        result = {}
        for uuid, tag in self.datastore.data['settings']['application']['tags'].items():
            result[uuid] = {
                'date_created': tag.get('date_created', 0),
                'notification_muted': tag.get('notification_muted', False),
                'title': tag.get('title', ''),
                'uuid': tag.get('uuid'),
                'overrides_watch': tag.get('overrides_watch', False),
                'restock_settings': tag.get('restock_settings', {})
            }

        return result, 200