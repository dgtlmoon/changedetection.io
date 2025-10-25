import os
from changedetectionio.strtobool import strtobool
from flask_restful import abort, Resource
from flask import request
import validators
from functools import wraps
from . import auth, validate_openapi_request


def default_content_type(content_type='text/plain'):
    """Decorator to set a default Content-Type header if none is provided."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.content_type:
                # Set default content type in the request environment
                request.environ['CONTENT_TYPE'] = content_type
            return f(*args, **kwargs)
        return wrapper
    return decorator


class Import(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @default_content_type('text/plain') #3547 #3542
    @validate_openapi_request('importWatches')
    def post(self):
        """Import a list of watched URLs."""

        extras = {}

        if request.args.get('proxy'):
            plist = self.datastore.proxy_list
            if not request.args.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400
            else:
                extras['proxy'] = request.args.get('proxy')

        dedupe = strtobool(request.args.get('dedupe', 'true'))

        tags = request.args.get('tag')
        tag_uuids = request.args.get('tag_uuids')

        if tag_uuids:
            tag_uuids = tag_uuids.split(',')

        urls = request.get_data().decode('utf8').splitlines()
        added = []
        allow_simplehost = not strtobool(os.getenv('BLOCK_SIMPLEHOSTS', 'False'))
        for url in urls:
            url = url.strip()
            if not len(url):
                continue

            # If hosts that only contain alphanumerics are allowed ("localhost" for example)
            if not validators.url(url, simple_host=allow_simplehost):
                return f"Invalid or unsupported URL - {url}", 400

            if dedupe and self.datastore.url_exists(url):
                continue

            new_uuid = self.datastore.add_watch(url=url, extras=extras, tag=tags, tag_uuids=tag_uuids)
            added.append(new_uuid)

        return added