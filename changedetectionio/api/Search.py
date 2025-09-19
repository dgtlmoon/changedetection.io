from flask_restful import Resource, abort
from flask import request
from . import auth, enrich_watch_model_for_api, validate_openapi_request

class Search(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('searchWatches')
    def get(self):
        """Search for watches by URL or title text."""
        query = request.args.get('q', '').strip()
        tag_limit = request.args.get('tag', '').strip()
        from changedetectionio.strtobool import strtobool
        partial = bool(strtobool(request.args.get('partial', '0'))) if 'partial' in request.args else False

        # Require a search query
        if not query:
            abort(400, message="Search query 'q' parameter is required")

        # Use the search function from the datastore
        matching_uuids = self.datastore.search_watches_for_url(query=query, tag_limit=tag_limit, partial=partial)

        # Build the response with watch details
        results = {}
        for uuid in matching_uuids:
            results[uuid] = enrich_watch_model_for_api(self.datastore.data['watching'].get(uuid))

        return results, 200

