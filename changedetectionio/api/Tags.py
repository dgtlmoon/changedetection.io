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
        from copy import deepcopy
        tag = deepcopy(self.datastore.data['settings']['application']['tags'].get(uuid))
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
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = True
            self.datastore.commit()
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = False
            self.datastore.commit()
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
        self.datastore.commit()

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

        # Validate notification_urls if provided
        if 'notification_urls' in request.json:
            from wtforms import ValidationError
            from changedetectionio.api.Notifications import validate_notification_urls
            try:
                notification_urls = request.json.get('notification_urls', [])
                validate_notification_urls(notification_urls)
            except ValidationError as e:
                return str(e), 400

        tag.update(request.json)
        self.datastore.commit()

        return "OK", 200


    @auth.check_token
    @validate_openapi_request('createTag')
    # Only cares for {'title': 'xxxx'}
    def post(self):
        """Create a single tag/group."""

        json_data = request.get_json()
        title = json_data.get("title",'').strip()


        new_uuid = self.datastore.add_tag(title=title)
        if new_uuid:
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
                'uuid': tag.get('uuid')
            }

        return result, 200