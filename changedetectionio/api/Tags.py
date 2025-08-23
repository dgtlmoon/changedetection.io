from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_handler
from flask_expects_json import expects_json
from flask_restful import abort, Resource

from flask import request
from . import auth

# Import schemas from __init__.py
from . import schema_tag, schema_create_tag, schema_update_tag


class Tag(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single tag
    # curl http://localhost:5000/api/v1/tag/<string:uuid>
    @auth.check_token
    def get(self, uuid):
        """Get data for a single tag/group, toggle notification muting, or recheck all."""
        from copy import deepcopy
        tag = deepcopy(self.datastore.data['settings']['application']['tags'].get(uuid))
        if not tag:
            abort(404, message=f'No tag exists with the UUID of {uuid}')

        if request.args.get('recheck'):
            # Recheck all, including muted
            # Get most overdue first
            i=0
            for k in sorted(self.datastore.data['watching'].items(), key=lambda item: item[1].get('last_checked', 0)):
                watch_uuid = k[0]
                watch = k[1]
                if not watch['paused'] and tag['uuid'] not in watch['tags']:
                    continue
                worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': watch_uuid}))
                i+=1

            return f"OK, {i} watches queued", 200

        if request.args.get('muted', '') == 'muted':
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = True
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = False
            return "OK", 200

        return tag

    @auth.check_token
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

        return 'OK', 204

    @auth.check_token
    @expects_json(schema_update_tag)
    def put(self, uuid):
        """Update tag information."""
        tag = self.datastore.data['settings']['application']['tags'].get(uuid)
        if not tag:
            abort(404, message='No tag exists with the UUID of {}'.format(uuid))

        tag.update(request.json)
        self.datastore.needs_write_urgent = True

        return "OK", 200


    @auth.check_token
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