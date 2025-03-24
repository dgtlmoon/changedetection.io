from flask_restful import Resource, abort
from flask import request
from . import auth

class Search(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self):
        """
        @api {get} /api/v1/search Search for watches
        @apiDescription Search watches by URL or title text
        @apiExample {curl} Example usage:
            curl "http://localhost:5000/api/v1/search?q=https://example.com/page1" -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:5000/api/v1/search?q=https://example.com/page1?tag=Favourites" -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            curl "http://localhost:5000/api/v1/search?q=https://example.com?partial=true" -H"x-api-key:813031b16330fe25e3780cf0325daa45"
        @apiName Search
        @apiGroup Watch Management
        @apiQuery {String} q Search query to match against watch URLs and titles
        @apiQuery {String} [tag] Optional name of tag to limit results (name not UUID)
        @apiQuery {String} [partial] Allow partial matching of URL query
        @apiSuccess (200) {Object} JSON Object containing matched watches
        """
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
            watch = self.datastore.data['watching'].get(uuid)
            results[uuid] = {
                'last_changed': watch.last_changed,
                'last_checked': watch['last_checked'],
                'last_error': watch['last_error'],
                'title': watch['title'],
                'url': watch['url'],
                'viewed': watch.viewed
            }

        return results, 200