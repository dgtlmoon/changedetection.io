from flask_expects_json import expects_json
from changedetectionio import queuedWatchMetaData
from flask_restful import abort, Resource
from flask import request, make_response
import validators
from . import auth
import copy

# See docs/README.md for rebuilding the docs/apidoc information

from . import api_schema

# Build a JSON Schema atleast partially based on our Watch model
from changedetectionio.model.Watch import base_config as watch_base_config
schema = api_schema.build_watch_json_schema(watch_base_config)

schema_create_watch = copy.deepcopy(schema)
schema_create_watch['required'] = ['url']

schema_update_watch = copy.deepcopy(schema)
schema_update_watch['additionalProperties'] = False

class Watch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single watch, excluding the history list (can be large)
    # curl http://localhost:4000/api/v1/watch/<string:uuid>
    # @todo - version2 - ?muted and ?paused should be able to be called together, return the watch struct not "OK"
    # ?recheck=true
    @auth.check_token
    def get(self, uuid):
        """
        @api {get} /api/v1/watch/:uuid Get a single watch data
        @apiDescription Retrieve watch information and set muted/paused status
        @apiExample {curl} Example usage:
            curl http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091?muted=unmuted"  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091?paused=unpaused"  -H"x-api-key:813031b16330fe25e3780cf0325daa45"
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
            self.update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid, 'skip_when_checksum_same': True}))
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
        watch['history_n'] = watch.history_n
        return watch

    @auth.check_token
    def delete(self, uuid):
        """
        @api {delete} /api/v1/watch/:uuid Delete a watch and related history
        @apiExample {curl} Example usage:
            curl http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X DELETE -H"x-api-key:813031b16330fe25e3780cf0325daa45"
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
            curl http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091 -X PUT -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"url": "https://my-nice.com" , "tag": "new list"}'

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
    # curl http://localhost:4000/api/v1/watch/<string:uuid>/history
    def get(self, uuid):
        """
        @api {get} /api/v1/watch/<string:uuid>/history Get a list of all historical snapshots available for a watch
        @apiDescription Requires `uuid`, returns list
        @apiExample {curl} Example usage:
            curl http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091/history -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json"
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
            curl http://localhost:4000/api/v1/watch/cc0cfffa-f449-477b-83ea-0caafd1dc091/history/1677092977 -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json"
        @apiName Get single snapshot content
        @apiGroup Watch History
        @apiSuccess (200) {String} OK
        @apiSuccess (404) {String} ERR Not found
        """
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if not len(watch.history):
            abort(404, message='Watch found but no history exists for the UUID {}'.format(uuid))

        if timestamp == 'latest':
            timestamp = list(watch.history.keys())[-1]

        # @todo - Check for UTF-8 compatability
        with open(watch.history[timestamp], 'r') as f:
            content = f.read()

        response = make_response(content, 200)
        response.mimetype = "text/plain"
        return response


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
            curl http://localhost:4000/api/v1/watch -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"url": "https://my-nice.com" , "tag": "nice list"}'
        @apiName Create
        @apiGroup Watch
        @apiSuccess (200) {String} OK Was created
        @apiSuccess (500) {String} ERR Some other error
        """

        json_data = request.get_json()
        url = json_data['url'].strip()

        if not validators.url(json_data['url'].strip()):
            return "Invalid or unsupported URL", 400

        if json_data.get('proxy'):
            plist = self.datastore.proxy_list
            if not json_data.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400

        extras = copy.deepcopy(json_data)
        del extras['url']

        new_uuid = self.datastore.add_watch(url=url, extras=extras)
        if new_uuid:
            self.update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid, 'skip_when_checksum_same': True}))
            return {'uuid': new_uuid}, 201
        else:
            return "Invalid or unsupported URL", 400

    @auth.check_token
    def get(self):
        """
        @api {get} /api/v1/watch List watches
        @apiDescription Return concise list of available watches and some very basic info
        @apiExample {curl} Example usage:
            curl http://localhost:4000/api/v1/watch -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            recheck_all=1 to recheck all
        @apiParam {String} [recheck_all]       Optional Set to =1 to force recheck of all watches
        @apiParam {String} [tag]               Optional name of tag to limit results
        @apiName ListWatches
        @apiGroup Watch Management
        @apiSuccess (200) {String} OK Was created
        """
        list = {}

        tag_limit = request.args.get('tag', None)
        for k, watch in self.datastore.data['watching'].items():
            if tag_limit:
                if not tag_limit.lower() in watch.all_tags:
                    continue

            list[k] = {'url': watch['url'],
                       'title': watch['title'],
                       'last_checked': watch['last_checked'],
                       'last_changed': watch.last_changed,
                       'last_error': watch['last_error']}

        if request.args.get('recheck_all'):
            for uuid in self.datastore.data['watching'].keys():
                self.update_q.put(queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid, 'skip_when_checksum_same': True}))
            return {'status': "OK"}, 200

        return list, 200

class SystemInfo(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    @auth.check_token
    def get(self):
        import time
        overdue_watches = []

        # Check all watches and report which have not been checked but should have been

        for uuid, watch in self.datastore.data.get('watching', {}).items():
            # see if now - last_checked is greater than the time that should have been
            # this is not super accurate (maybe they just edited it) but better than nothing
            t = watch.threshold_seconds()
            if not t:
                # Use the system wide default
                t = self.datastore.threshold_seconds

            time_since_check = time.time() - watch.get('last_checked')

            # Allow 5 minutes of grace time before we decide it's overdue
            if time_since_check - (5 * 60) > t:
                overdue_watches.append(uuid)

        return {
                   'queue_size': self.update_q.qsize(),
                   'overdue_watches': overdue_watches,
                   'uptime': round(time.time() - self.datastore.start_time, 2),
                   'watch_count': len(self.datastore.data.get('watching', {}))
               }, 200
