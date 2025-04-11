from flask_expects_json import expects_json
from flask_restful import Resource
from . import auth
from flask_restful import abort, Resource
from flask import request
from . import auth

# Import schemas from __init__.py
from . import schema_notification_urls, schema_create_notification_url

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
    @expects_json(schema_create_notification_url)    
    def post(self):
        """
        @api {post} /api/v1/notifications Create a single Notification URL
        @apiDescription Add a new the notification URL to the configuration
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/notifications -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"notification_url": "posts://service.com?yes=please&+custom-header=hello"}'
        @apiName Create
        @apiGroup Notifications
        @apiSuccess (201) {String} OK Was created
        @apiSuccess (500) {String} ERR Some other error
        """

        json_data = request.get_json()
        notification_url = json_data.get("notification_url",'').strip()

        new_notification_url = self.datastore.add_notification_url(notification_url)
        if new_notification_url:
            return {'notification_url': new_notification_url}, 201
        else:
            return "Invalid or unsupported notification_url", 400
        
    @auth.check_token
    def delete(self):
        """
        @api {delete} /api/v1/notifications Delete a single Notification URL
        @apiDescription Deletes a specific notification URL from the configuration
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/notifications -X DELETE -H"x-api-key:813031b16330fe25e3780cf0325daa45" -H "Content-Type: application/json" -d '{"notification_url": "your-url-here"}'
        @apiParam {String} notification_url The notification URL to delete.
        @apiName Delete
        @apiGroup Notifications
        @apiSuccess (204) {String} OK Was deleted
        @apiError (400) {String} No notification URL found matching the provided input.
        """

        json_data = request.get_json()
        notification_url = json_data.get("notification_url",'').strip()
        
        notification_urls = self.datastore.data['settings']['application'].get('notification_urls', [])

        if notification_url not in notification_urls:
            abort(400, message=f"No notification URL found matching: {notification_url}")

        # Remove the URL
        notification_urls.remove(notification_url)

        # Save the updated list back
        self.datastore.data['settings']['application']['notification_urls'] = notification_urls

        # Mark for saving
        self.datastore.needs_write = True

        return 'OK', 204