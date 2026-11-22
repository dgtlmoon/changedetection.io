from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_pool
from flask_restful import abort, Resource
from loguru import logger

import threading
from flask import request
from . import auth

from . import validate_openapi_request, strip_internal_api_fields


def validate_tag_colour(json_data):
    """Return an error message when tag_colour is set to anything but a hex colour.

    The value is rendered into a <style> block, so anything else is CSS injection.
    The OpenAPI schema carries the same pattern, this is the belt to that's braces.
    """
    from changedetectionio.blueprint.tags.colour import is_safe_css_colour

    tag_colour = json_data.get('tag_colour')
    if tag_colour and not is_safe_css_colour(tag_colour):
        return "tag_colour: must be a hex colour, for example #4f8ef7"

    return None


class Tag(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single tag
    # curl http://localhost:5000/api/v1/tag/<uuid_str:uuid>
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

        # Never expose `__`-prefixed transient/internal fields
        return strip_internal_api_fields(clean_tag)

    @auth.check_token
    @validate_openapi_request('deleteTag')
    def delete(self, uuid):
        """Delete a tag/group and remove it from all watches."""
        from changedetectionio.api.operations import ApiError, delete_tag
        try:
            delete_tag(self.datastore, uuid)
        except ApiError as e:
            abort(e.status, message=e.message)
        return 'OK', 204

    @auth.check_token
    @validate_openapi_request('updateTag')
    def put(self, uuid):
        """Update tag information."""
        from changedetectionio.api.operations import ApiError, update_tag
        if not self.datastore.data['settings']['application']['tags'].get(uuid):
            abort(404, message='No tag exists with the UUID of {}'.format(uuid))
        try:
            update_tag(self.datastore, uuid, request.json)
        except ApiError as e:
            return e.message, e.status
        return "OK", 200


    @auth.check_token
    @validate_openapi_request('createTag')
    def post(self):
        """Create a single tag/group."""
        from changedetectionio.api.operations import ApiError, create_tag
        try:
            new_uuid = create_tag(self.datastore, request.get_json())
        except ApiError as e:
            return e.message, e.status
        return {'uuid': new_uuid}, 201

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