import os
from changedetectionio.strtobool import strtobool

from flask_expects_json import expects_json
from changedetectionio import queuedWatchMetaData
from changedetectionio import worker_handler
from flask_restful import abort, Resource
from flask import request, make_response, send_from_directory
import validators
from . import auth
import copy

# Import schemas from __init__.py
from . import schema, schema_create_watch, schema_update_watch


class Watch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single watch, excluding the history list (can be large)
    # curl http://localhost:5000/api/v1/watch/<string:uuid>
    # @todo - version2 - ?muted and ?paused should be able to be called together, return the watch struct not "OK"
    # ?recheck=true
    @auth.check_token
    def get(self, uuid):
        """
        @api {get} /api/v1/watch/:uuid Single watch - get data, recheck, pause, mute.
        @apiDescription Retrieve watch information and set muted/paused status
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091?muted=unmuted"  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091?paused=unpaused"  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiName Watch
        @apiGroup Watch
        @apiParam {uuid} uuid Watch unique ID.
        @apiQuery {Boolean} [recheck] Recheck this watch `recheck=1`
        @apiQuery {String} [paused] =`paused` or =`unpaused` , Sets the PAUSED state
        @apiQuery {String} [muted] =`muted` or =`unmuted` , Sets the MUTE NOTIFICATIONS state
        @apiSuccess (200) {String} OK When paused/muted/recheck operation OR full JSON object of the watch
        @apiSuccess (200) {JSON} WatchJSON JSON Full JSON object of the watch
        """
        from copy import deepcopy
        watch = deepcopy(self.datastore.data['watching'].get(uuid))
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if request.args.get('recheck'):
            worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            return "OK", 200
        if request.args.get('paused', '') == 'paused':
            self.datastore.data['watching'].get(uuid).pause()
            return "OK", 200
        elif request.args.get('paused', '') == 'unpaused':
            self.datastore.data['watching'].get(uuid).unpause()
            return "OK", 200
        if request.args.get('muted', '') == 'muted':
            self.datastore.data['watching'].get(uuid).mute()
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            self.datastore.data['watching'].get(uuid).unmute()
            return "OK", 200

        # Return without history, get that via another API call
        # Properties are not returned as a JSON, so add the required props manually
        watch['history_n'] = watch.history_n
        # attr .last_changed will check for the last written text snapshot on change
        watch['last_changed'] = watch.last_changed
        watch['viewed'] = watch.viewed
        return watch

    @auth.check_token
    def delete(self, uuid):
        """
        @api {delete} /api/v1/watch/:uuid Delete a watch and related history
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X DELETE -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiParam {uuid} uuid Watch unique ID.
        @apiName Delete
        @apiGroup Watch
        @apiSuccess (200) {String} OK Was deleted
        """
        if not self.datastore.data['watching'].get(uuid):
            abort(400, message='No watch exists with the UUID of {}'.format(uuid))

        self.datastore.delete(uuid)
        return 'OK', 204

    @auth.check_token
    @expects_json(schema_update_watch)
    def put(self, uuid):
        """
        @api {put} /api/v1/watch/:uuid Update watch information
        @apiExample {curl} Example usage:
            Update (PUT)
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X PUT -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"url": "https://my-nice.com" , "tag": "new list"}'

        @apiDescription Updates an existing watch using JSON, accepts the same structure as returned in <a href="#api-Watch-Watch">get single watch information</a>
        @apiParam {uuid} uuid Watch unique ID.
        @apiName Update a watch
        @apiGroup Watch
        @apiSuccess (200) {String} OK Was updated
        @apiSuccess (500) {String} ERR Some other error
        """
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if request.json.get('proxy'):
            plist = self.datastore.proxy_list
            if not request.json.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400

        watch.update(request.json)

        return "OK", 200


class WatchHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    # Get a list of available history for a watch by UUID
    # curl http://localhost:5000/api/v1/watch/<string:uuid>/history
    @auth.check_token
    def get(self, uuid):
        """
        @api {get} /api/v1/watch/<string:uuid>/history Get a list of all historical snapshots available for a watch
        @apiDescription Requires `uuid`, returns list
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091/history -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json"
            {
                "1676649279": "/tmp/data/6a4b7d5c-fee4-4616-9f43-4ac97046b595/cb7e9be8258368262246910e6a2a4c30.txt",
                "1677092785": "/tmp/data/6a4b7d5c-fee4-4616-9f43-4ac97046b595/e20db368d6fc633e34f559ff67bb4044.txt",
                "1677103794": "/tmp/data/6a4b7d5c-fee4-4616-9f43-4ac97046b595/02efdd37dacdae96554a8cc85dc9c945.txt"
            }
        @apiName Get list of available stored snapshots for watch
        @apiGroup Watch History
        @apiSuccess (200) {String} OK
        @apiSuccess (404) {String} ERR Not found
        """
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))
        return watch.history, 200


class WatchSingleHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self, uuid, timestamp):
        """
        @api {get} /api/v1/watch/<string:uuid>/history/<int:timestamp> Get single snapshot from watch
        @apiDescription Requires watch `uuid` and `timestamp`. `timestamp` of "`latest`" for latest available snapshot, or <a href="#api-Watch_History-Get_list_of_available_stored_snapshots_for_watch">use the list returned here</a>
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091/history/1677092977 -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json"
        @apiName Get single snapshot content
        @apiGroup Watch History
        @apiParam {String} [html]       Optional Set to =1 to return the last HTML (only stores last 2 snapshots, use `latest` as timestamp)
        @apiSuccess (200) {String} OK
        @apiSuccess (404) {String} ERR Not found
        """
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f"No watch exists with the UUID of {uuid}")

        if not len(watch.history):
            abort(404, message=f"Watch found but no history exists for the UUID {uuid}")

        if timestamp == 'latest':
            timestamp = list(watch.history.keys())[-1]

        if request.args.get('html'):
            content = watch.get_fetched_html(timestamp)
            if content:
                response = make_response(content, 200)
                response.mimetype = "text/html"
            else:
                response = make_response("No content found", 404)
                response.mimetype = "text/plain"
        else:
            content = watch.get_history_snapshot(timestamp)
            response = make_response(content, 200)
            response.mimetype = "text/plain"

        return response

class WatchFavicon(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self, uuid):
        """
        @api {get} /api/v1/watch/<string:uuid>/favicon Get Favicon for a watch
        @apiDescription Requires watch `uuid`
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091/favicon -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiName Get latest Favicon
        @apiGroup Watch History
        @apiSuccess (200) {String} OK
        @apiSuccess (404) {String} ERR Not found
        """
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f"No watch exists with the UUID of {uuid}")

        favicon_filename = watch.get_favicon_filename()
        if favicon_filename:
            try:
                import magic
                mime = magic.from_file(
                    os.path.join(watch.watch_data_dir, favicon_filename),
                    mime=True
                )
            except ImportError:
                # Fallback, no python-magic
                import mimetypes
                mime, encoding = mimetypes.guess_type(favicon_filename)

            response = make_response(send_from_directory(watch.watch_data_dir, favicon_filename))
            response.headers['Content-type'] = mime
            response.headers['Cache-Control'] = 'max-age=300, must-revalidate'  # Cache for 5 minutes, then revalidate
            return response

        abort(404, message=f'No Favicon available for {uuid}')


class CreateWatch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    @auth.check_token
    @expects_json(schema_create_watch)
    def post(self):
        """
        @api {post} /api/v1/watch Create a single watch
        @apiDescription Requires atleast `url` set, can accept the same structure as <a href="#api-Watch-Watch">get single watch information</a> to create.
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"url": "https://my-nice.com" , "tag": "nice list"}'
        @apiName Create
        @apiGroup Watch
        @apiSuccess (200) {String} OK Was created
        @apiSuccess (500) {String} ERR Some other error
        """

        json_data = request.get_json()
        url = json_data['url'].strip()

        # If hosts that only contain alphanumerics are allowed ("localhost" for example)
        allow_simplehost = not strtobool(os.getenv('BLOCK_SIMPLEHOSTS', 'False'))
        if not validators.url(url, simple_host=allow_simplehost):
            return "Invalid or unsupported URL", 400

        if json_data.get('proxy'):
            plist = self.datastore.proxy_list
            if not json_data.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400

        extras = copy.deepcopy(json_data)

        # Because we renamed 'tag' to 'tags' but don't want to change the API (can do this in v2 of the API)
        tags = None
        if extras.get('tag'):
            tags = extras.get('tag')
            del extras['tag']

        del extras['url']

        new_uuid = self.datastore.add_watch(url=url, extras=extras, tag=tags)
        if new_uuid:
            worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
            return {'uuid': new_uuid}, 201
        else:
            return "Invalid or unsupported URL", 400

    @auth.check_token
    def get(self):
        """
        @api {get} /api/v1/watch List watches
        @apiDescription Return concise list of available watches and some very basic info
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/watch -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            {
                "6a4b7d5c-fee4-4616-9f43-4ac97046b595": {
                    "last_changed": 1677103794,
                    "last_checked": 1677103794,
                    "last_error": false,
                    "title": "",
                    "url": "http://www.quotationspage.com/random.php"
                },
                "e6f5fd5c-dbfe-468b-b8f3-f9d6ff5ad69b": {
                    "last_changed": 0,
                    "last_checked": 1676662819,
                    "last_error": false,
                    "title": "QuickLook",
                    "url": "https://github.com/QL-Win/QuickLook/tags"
                }
            }

        @apiParam {String} [recheck_all]       Optional Set to =1 to force recheck of all watches
        @apiParam {String} [tag]               Optional name of tag to limit results
        @apiName ListWatches
        @apiGroup Watch Management
        @apiSuccess (200) {String} OK JSON dict
        """
        list = {}

        tag_limit = request.args.get('tag', '').lower()
        for uuid, watch in self.datastore.data['watching'].items():
            # Watch tags by name (replace the other calls?)
            tags = self.datastore.get_all_tags_for_watch(uuid=uuid)
            if tag_limit and not any(v.get('title').lower() == tag_limit for k, v in tags.items()):
                continue

            list[uuid] = {
                'last_changed': watch.last_changed,
                'last_checked': watch['last_checked'],
                'last_error': watch['last_error'],
                'title': watch['title'],
                'url': watch['url'],
                'viewed': watch.viewed
            }

        if request.args.get('recheck_all'):
            for uuid in self.datastore.data['watching'].keys():
                worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            return {'status': "OK"}, 200

        return list, 200