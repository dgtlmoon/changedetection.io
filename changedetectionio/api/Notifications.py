from flask_expects_json import expects_json
from flask_restful import Resource
from . import auth
from flask_restful import abort, Resource
from flask import request
from . import auth
from . import schema_create_notification_urls, schema_delete_notification_urls

class Notifications(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self):
        """
        @api {get} /api/v1/notifications Return Notification URL List
        @apiDescription Return the Notification URL List from the configuration
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/notifications -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            HTTP/1.0 200
            {
                'notification_urls': ["notification-urls-list"]
            }
        @apiName Get
        @apiGroup Notifications
        """

        notification_urls = self.datastore.data.get('settings', {}).get('application', {}).get('notification_urls', [])        

        return {
                'notification_urls': notification_urls,
               }, 200
    
    @auth.check_token
    @expects_json(schema_create_notification_urls)
    def post(self):
        """
        @api {post} /api/v1/notifications Create Notification URLs
        @apiDescription Add one or more notification URLs from the configuration
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/notifications/batch -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"notification_urls": ["url1", "url2"]}'
        @apiName CreateBatch
        @apiGroup Notifications
        @apiSuccess (201) {Object[]} notification_urls List of added notification URLs
        @apiError (400) {String} Invalid input
        """

        json_data = request.get_json()
        notification_urls = json_data.get("notification_urls", [])

        from wtforms import ValidationError
        try:
            validate_notification_urls(notification_urls)
        except ValidationError as e:
            return str(e), 400

        added_urls = []

        for url in notification_urls:
            clean_url = url.strip()
            added_url = self.datastore.add_notification_url(clean_url)
            if added_url:
                added_urls.append(added_url)

        if not added_urls:
            return "No valid notification URLs were added", 400

        return {'notification_urls': added_urls}, 201
    
    @auth.check_token
    @expects_json(schema_create_notification_urls)
    def put(self):
        """
        @api {put} /api/v1/notifications Replace Notification URLs
        @apiDescription Replace all notification URLs with the provided list (can be empty)
        @apiExample {curl} Example usage:
            curl -X PUT http://localhost:5000/api/v1/notifications -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"notification_urls": ["url1", "url2"]}'
        @apiName Replace
        @apiGroup Notifications
        @apiSuccess (200) {Object[]} notification_urls List of current notification URLs
        @apiError (400) {String} Invalid input
        """
        json_data = request.get_json()
        notification_urls = json_data.get("notification_urls", [])

        from wtforms import ValidationError
        try:
            validate_notification_urls(notification_urls)
        except ValidationError as e:
            return str(e), 400
        
        if not isinstance(notification_urls, list):
            return "Invalid input format", 400

        clean_urls = [url.strip() for url in notification_urls if isinstance(url, str)]
        self.datastore.data['settings']['application']['notification_urls'] = clean_urls
        self.datastore.needs_write = True

        return {'notification_urls': clean_urls}, 200
        
    @auth.check_token
    @expects_json(schema_delete_notification_urls)
    def delete(self):
        """
        @api {delete} /api/v1/notifications Delete Notification URLs
        @apiDescription Deletes one or more notification URLs from the configuration
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/notifications -X DELETE -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"notification_urls": ["url1", "url2"]}'
        @apiParam {String[]} notification_urls The notification URLs to delete.
        @apiName Delete
        @apiGroup Notifications
        @apiSuccess (204) {String} OK Deleted
        @apiError (400) {String} No matching notification URLs found.
        """

        json_data = request.get_json()
        urls_to_delete = json_data.get("notification_urls", [])
        if not isinstance(urls_to_delete, list):
            abort(400, message="Expected a list of notification URLs.")

        notification_urls = self.datastore.data['settings']['application'].get('notification_urls', [])
        deleted = []

        for url in urls_to_delete:
            clean_url = url.strip()
            if clean_url in notification_urls:
                notification_urls.remove(clean_url)
                deleted.append(clean_url)

        if not deleted:
            abort(400, message="No matching notification URLs found.")

        self.datastore.data['settings']['application']['notification_urls'] = notification_urls
        self.datastore.needs_write = True

        return 'OK', 204
    
def validate_notification_urls(notification_urls):
    from changedetectionio.forms import ValidateAppRiseServers
    validator = ValidateAppRiseServers()
    class DummyForm: pass
    dummy_form = DummyForm()
    field = type("Field", (object,), {"data": notification_urls, "gettext": lambda self, x: x})()
    validator(dummy_form, field)