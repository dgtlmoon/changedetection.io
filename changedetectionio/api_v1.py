from flask_restful import reqparse, abort, Api, Resource
from flask import request
# https://www.w3.org/Protocols/rfc2616/rfc2616-sec10.html

class Watch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single watch, excluding the history list (can be large)
    # curl http://localhost:4000/api/v1/watch/<string:uuid>
    # ?recheck=true
    def get(self, uuid):
        from copy import deepcopy
        watch = deepcopy(self.datastore.data['watching'].get(uuid))
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if request.args.get('recheck'):
            self.update_q.put(uuid)
            return "OK", 200

        # Return without history, get that via another API call
        watch['history_n'] = len(watch['history'])
        del (watch['history'])
        return watch

    def delete(self, uuid):
        if not self.datastore.data['watching'].get(uuid):
            abort(400, message='No watch exists with the UUID of {}'.format(uuid))

        self.datastore.delete(uuid)
        return '', 204




class WatchHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    # Get a list of available history for a watch by UUID
    # curl http://localhost:4000/api/v1/watch/<string:uuid>/history
    def get(self, uuid):
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))
        return watch['history'], 200


class WatchSingleHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    def get(self, uuid, timestamp):
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        return watch

    def delete(self, uuid, timestamp):
        if not self.datastore.data['watching'].get(uuid):
            abort(400, message='No watch exists with the UUID of {}'.format(uuid))

        self.datastore.delete(uuid)
        return '', 204

class CreateWatch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    def post(self):
        # curl http://localhost:4000/api/v1/watch -H "Content-Type: application/json" -d '{"url": "https://my-nice.com", "tag": "one, two" }'
        json_data = request.get_json()
        tag = json_data['tag'].strip() if json_data.get('tag') else ''
        new_uuid = self.datastore.add_watch(url=json_data['url'].strip(), tag=tag)
        return new_uuid, 201

    # Return concise list of available watches and some very basic info
    # curl http://localhost:4000/api/v1/watch|python -mjson.tool
    # ?recheck=all to recheck all
    def get(self):
        list = {}
        for k, v in self.datastore.data['watching'].items():
            list[k] = {'url': v['url'],
                       'title': v['title'],
                       'last_checked': v['last_checked'],
                       'last_changed': v['last_changed']}

        if request.args.get('recheck'):
            for uuid in self.datastore.data['watching'].items():
                self.update_q.put(uuid)
            return "OK", 200

        return list, 200
