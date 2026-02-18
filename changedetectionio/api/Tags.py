from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_pool
from flask_restful import abort, Resource
from loguru import logger

import threading
from flask import request
from . import auth

from . import validate_openapi_request


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

        # Filter out Watch-specific runtime fields that don't apply to Tags (yet)
        # TODO: Future enhancement - aggregate these values from all Watches that have this tag:
        #   - check_count: sum of all watches' check_count
        #   - last_checked: most recent last_checked from all watches
        #   - last_changed: most recent last_changed from all watches
        #   - consecutive_filter_failures: count of watches with failures
        #   - etc.
        # These come from watch_base inheritance but currently have no meaningful value for Tags
        watch_only_fields = {
            'browser_steps_last_error_step', 'check_count', 'consecutive_filter_failures',
            'content-type', 'fetch_time', 'last_changed', 'last_checked', 'last_error',
            'last_notification_error', 'last_viewed', 'notification_alert_count',
            'page_title', 'previous_md5', 'remote_server_reply'
        }

        # Create clean tag dict without Watch-specific fields
        clean_tag = {k: v for k, v in tag.items() if k not in watch_only_fields}

        return clean_tag

    @auth.check_token
    @validate_openapi_request('deleteTag')
    def delete(self, uuid):
        """Delete a tag/group and remove it from all watches."""
        if not self.datastore.data['settings']['application']['tags'].get(uuid):
            abort(400, message='No tag exists with the UUID of {}'.format(uuid))

        # Delete the tag, and any tag reference
        del self.datastore.data['settings']['application']['tags'][uuid]

        # Remove tag from all watches
        for watch_uuid, watch in self.datastore.data['watching'].items():
            if watch.get('tags') and uuid in watch['tags']:
                watch['tags'].remove(uuid)
                watch.commit()

        return 'OK', 204

    @auth.check_token
    @validate_openapi_request('updateTag')
    def put(self, uuid):
        """Update tag information."""
        tag = self.datastore.data['settings']['application']['tags'].get(uuid)
        if not tag:
            abort(404, message='No tag exists with the UUID of {}'.format(uuid))

        # Make a mutable copy of request.json for modification
        json_data = dict(request.json)

        # Validate notification_urls if provided
        if 'notification_urls' in json_data:
            from wtforms import ValidationError
            from changedetectionio.api.Notifications import validate_notification_urls
            try:
                notification_urls = json_data.get('notification_urls', [])
                validate_notification_urls(notification_urls)
            except ValidationError as e:
                return str(e), 400

        # Filter out readOnly fields (extracted from OpenAPI spec Tag schema)
        # These are system-managed fields that should never be user-settable
        from . import get_readonly_tag_fields
        readonly_fields = get_readonly_tag_fields()

        # Tag model inherits from watch_base but has no @property attributes of its own
        # So we only need to filter readOnly fields
        for field in readonly_fields:
            json_data.pop(field, None)

        # Validate remaining fields - reject truly unknown fields
        # Get valid fields from Tag schema
        from . import get_tag_schema_properties
        valid_fields = set(get_tag_schema_properties().keys())

        # Check for unknown fields
        unknown_fields = set(json_data.keys()) - valid_fields
        if unknown_fields:
            return f"Unknown field(s): {', '.join(sorted(unknown_fields))}", 400

        tag.update(json_data)
        tag.commit()

        # Clear checksums for all watches using this tag to force reprocessing
        # Tag changes affect inherited configuration
        cleared_count = self.datastore.clear_checksums_for_tag(uuid)
        logger.info(f"Tag {uuid} updated via API, cleared {cleared_count} watch checksums")

        return "OK", 200


    @auth.check_token
    @validate_openapi_request('createTag')
    def post(self):
        """Create a single tag/group."""

        json_data = request.get_json()
        title = json_data.get("title",'').strip()

        # Validate that only valid fields are provided
        # Get valid fields from Tag schema
        from . import get_tag_schema_properties
        valid_fields = set(get_tag_schema_properties().keys())

        # Check for unknown fields
        unknown_fields = set(json_data.keys()) - valid_fields
        if unknown_fields:
            return f"Unknown field(s): {', '.join(sorted(unknown_fields))}", 400

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