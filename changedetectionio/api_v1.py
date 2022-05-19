from flask_restful import reqparse, abort, Api, Resource
from flask import request
# https://www.w3.org/Protocols/rfc2616/rfc2616-sec10.html

class Watch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    def get(self, uuid):
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

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

    def get(self, uuid, timestamp):
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        def delete(self, timestamp):
            # Delete all history by timestamp or 'all'
            return '', 204
        return watch

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

    def post(self):
        # "Fields" for validation?
        tag = request.form.get('tag', '')
        new_uuid = self.datastore.add_watch(url=request.form.get('url').strip(), tag=tag)
        return new_uuid, 201


