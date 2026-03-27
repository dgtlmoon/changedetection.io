from flask_restful import Resource, abort
from flask import request
from . import auth, validate_openapi_request

_API_PROFILE_NAME = "API Default"

def _get_api_profile(datastore):
    """Return (uuid, profile_dict) for the API-managed system profile, or (None, None)."""
    profiles = datastore.data['settings']['application'].get('notification_profile_data', {})
    for uid, p in profiles.items():
        if p.get('name') == _API_PROFILE_NAME:
            return uid, p
    return None, None


def _ensure_api_profile(datastore, urls):
    """Create or update the API Default profile and ensure it's linked to system."""
    import uuid as uuid_mod

    app = datastore.data['settings']['application']
    app.setdefault('notification_profile_data', {})
    app.setdefault('notification_profiles', [])

    uid, profile = _get_api_profile(datastore)
    if uid is None:
        uid = str(uuid_mod.uuid4())
        profile = {'uuid': uid, 'name': _API_PROFILE_NAME, 'type': 'apprise', 'config': {}}
        app['notification_profile_data'][uid] = profile

    profile['config']['notification_urls'] = urls

    if uid not in app['notification_profiles']:
        app['notification_profiles'].append(uid)

    datastore.needs_write = True
    return uid, profile


class Notifications(Resource):
    def __init__(self, **kwargs):
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('getNotifications')
    def get(self):
        """Return Notification URL List (from the API Default profile)."""
        _, profile = _get_api_profile(self.datastore)
        urls = profile['config'].get('notification_urls', []) if profile else []
        return {'notification_urls': urls}, 200

    @auth.check_token
    @validate_openapi_request('addNotifications')
    def post(self):
        """Add Notification URLs to the API Default profile."""
        json_data = request.get_json()
        notification_urls = json_data.get("notification_urls", [])

        from wtforms import ValidationError
        try:
            validate_notification_urls(notification_urls)
        except ValidationError as e:
            return str(e), 400

        _, profile = _get_api_profile(self.datastore)
        existing = list(profile['config'].get('notification_urls', []) if profile else [])

        added = []
        for url in notification_urls:
            clean = url.strip()
            if clean and clean not in existing:
                existing.append(clean)
                added.append(clean)

        if not added:
            return "No valid notification URLs were added", 400

        _ensure_api_profile(self.datastore, existing)
        self.datastore.commit()
        return {'notification_urls': existing}, 201

    @auth.check_token
    @validate_openapi_request('replaceNotifications')
    def put(self):
        """Replace Notification URLs in the API Default profile."""
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

        if clean_urls:
            _ensure_api_profile(self.datastore, clean_urls)
        else:
            # Empty list: remove the profile entirely
            uid, _ = _get_api_profile(self.datastore)
            if uid:
                app = self.datastore.data['settings']['application']
                app['notification_profile_data'].pop(uid, None)
                if uid in app.get('notification_profiles', []):
                    app['notification_profiles'].remove(uid)
                self.datastore.needs_write = True

        self.datastore.commit()
        return {'notification_urls': clean_urls}, 200

    @auth.check_token
    @validate_openapi_request('deleteNotifications')
    def delete(self):
        """Delete specific Notification URLs from the API Default profile."""
        json_data = request.get_json()
        urls_to_delete = json_data.get("notification_urls", [])
        if not isinstance(urls_to_delete, list):
            abort(400, message="Expected a list of notification URLs.")

        uid, profile = _get_api_profile(self.datastore)
        if not profile:
            abort(400, message="No matching notification URLs found.")

        current = list(profile['config'].get('notification_urls', []))
        deleted = []
        for url in urls_to_delete:
            clean = url.strip()
            if clean in current:
                current.remove(clean)
                deleted.append(clean)

        if not deleted:
            abort(400, message="No matching notification URLs found.")

        profile['config']['notification_urls'] = current
        self.datastore.needs_write = True
        self.datastore.commit()
        return 'OK', 204


def validate_notification_urls(notification_urls):
    from changedetectionio.forms import ValidateAppRiseServers
    validator = ValidateAppRiseServers()
    class DummyForm: pass
    dummy_form = DummyForm()
    field = type("Field", (object,), {"data": notification_urls, "gettext": lambda self, x: x})()
    validator(dummy_form, field)
