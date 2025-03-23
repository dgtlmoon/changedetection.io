import os
from changedetectionio.strtobool import strtobool
from flask_restful import abort, Resource
from flask import request
import validators
from . import auth


class Import(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    def post(self):
        """
        @api {post} /api/v1/import Import a list of watched URLs
        @apiDescription Accepts a line-feed separated list of URLs to import, additionally with ?tag_uuids=(tag  id), ?tag=(name), ?proxy={key}, ?dedupe=true (default true) one URL per line.
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/import --data-binary @list-of-sites.txt -H"x-api-key:8a111a21bc2f8f1dd9b9353bbd46049a"
        @apiName Import
        @apiGroup Watch
        @apiSuccess (200) {List} OK List of watch UUIDs added
        @apiSuccess (500) {String} ERR Some other error
        """

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