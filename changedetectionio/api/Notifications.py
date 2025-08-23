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
        """Return Notification URL List."""

        notification_urls = self.datastore.data.get('settings', {}).get('application', {}).get('notification_urls', [])        

        return {
                'notification_urls': notification_urls,
               }, 200
    
    @auth.check_token
    @expects_json(schema_create_notification_urls)
    def post(self):
        """Create Notification URLs."""

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
        """Replace Notification URLs."""
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
        """Delete Notification URLs."""

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