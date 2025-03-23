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

    # Get information about a single tag
    # curl http://localhost:5000/api/v1/tag/<string:uuid>
    @auth.check_token
    def get(self, uuid):
        """
        @api {get} /api/v1/tag/:uuid Single tag - get data or toggle notification muting.
        @apiDescription Retrieve tag information and set notification_muted status
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/tag/cc0cfffa-f449-477b-83ea-0caafd1dc091 -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:5000/api/v1/tag/cc0cfffa-f449-477b-83ea-0caafd1dc091?muted=muted" -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiName Tag
        @apiGroup Tag
        @apiParam {uuid} uuid Tag unique ID.
        @apiQuery {String} [muted] =`muted` or =`unmuted` , Sets the MUTE NOTIFICATIONS state
        @apiSuccess (200) {String} OK When muted operation OR full JSON object of the tag
        @apiSuccess (200) {JSON} TagJSON JSON Full JSON object of the tag
        """
        from copy import deepcopy
        tag = deepcopy(self.datastore.data['settings']['application']['tags'].get(uuid))
        if not tag:
            abort(404, message=f'No tag exists with the UUID of {uuid}')

        if request.args.get('muted', '') == 'muted':
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = True
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            self.datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = False
            return "OK", 200

        return tag

    @auth.check_token
    def delete(self, uuid):
        """
        @api {delete} /api/v1/tag/:uuid Delete a tag and remove it from all watches
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/tag/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X DELETE -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiParam {uuid} uuid Tag unique ID.
        @apiName DeleteTag
        @apiGroup Tag
        @apiSuccess (200) {String} OK Was deleted
        """
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
        """
        @api {put} /api/v1/tag/:uuid Update tag information
        @apiExample {curl} Example usage:
            Update (PUT)
            curl http://localhost:5000/api/v1/tag/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X PUT -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"title": "New Tag Title"}'

        @apiDescription Updates an existing tag using JSON
        @apiParam {uuid} uuid Tag unique ID.
        @apiName UpdateTag
        @apiGroup Tag
        @apiSuccess (200) {String} OK Was updated
        @apiSuccess (500) {String} ERR Some other error
        """
        tag = self.datastore.data['settings']['application']['tags'].get(uuid)
        if not tag:
            abort(404, message='No tag exists with the UUID of {}'.format(uuid))

        tag.update(request.json)
        self.datastore.needs_write_urgent = True

        return "OK", 200


    @auth.check_token
    # Only cares for {'title': 'xxxx'}
    def post(self):
        """
        @api {post} /api/v1/watch Create a single tag
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"name": "Work related"}'
        @apiName Create
        @apiGroup Tag
        @apiSuccess (200) {String} OK Was created
        @apiSuccess (500) {String} ERR Some other error
        """

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
        """
        @api {get} /api/v1/tags List tags
        @apiDescription Return list of available tags
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/tags -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            {
                "cc0cfffa-f449-477b-83ea-0caafd1dc091": {
                    "title": "Tech News",
                    "notification_muted": false,
                    "date_created": 1677103794
                },
                "e6f5fd5c-dbfe-468b-b8f3-f9d6ff5ad69b": {
                    "title": "Shopping",
                    "notification_muted": true,
                    "date_created": 1676662819
                }
            }
        @apiName ListTags
        @apiGroup Tag Management
        @apiSuccess (200) {String} OK JSON dict
        """
        result = {}
        for uuid, tag in self.datastore.data['settings']['application']['tags'].items():
            result[uuid] = {
                'date_created': tag.get('date_created', 0),
                'notification_muted': tag.get('notification_muted', False),
                'title': tag.get('title', ''),
                'uuid': tag.get('uuid')
            }

        return result, 200