import copy
import yaml
import functools
from flask import request, abort
from openapi_core import OpenAPI
from openapi_core.contrib.flask import FlaskOpenAPIRequest
from . import api_schema
from ..model import watch_base

# Build a JSON Schema atleast partially based on our Watch model
watch_base_config = watch_base()
schema = api_schema.build_watch_json_schema(watch_base_config)

schema_create_watch = copy.deepcopy(schema)
schema_create_watch['required'] = ['url']

schema_update_watch = copy.deepcopy(schema)
schema_update_watch['additionalProperties'] = False

# Tag schema is also based on watch_base since Tag inherits from it
schema_tag = copy.deepcopy(schema)
schema_create_tag = copy.deepcopy(schema_tag)
schema_create_tag['required'] = ['title']
schema_update_tag = copy.deepcopy(schema_tag)
schema_update_tag['additionalProperties'] = False

schema_notification_urls = copy.deepcopy(schema)
schema_create_notification_urls = copy.deepcopy(schema_notification_urls)
schema_create_notification_urls['required'] = ['notification_urls']
schema_delete_notification_urls = copy.deepcopy(schema_notification_urls)
schema_delete_notification_urls['required'] = ['notification_urls']

# Load OpenAPI spec for validation
_openapi_spec = None

def get_openapi_spec():
    global _openapi_spec
    if _openapi_spec is None:
        import os
        spec_path = os.path.join(os.path.dirname(__file__), '../../docs/api-spec.yaml')
        with open(spec_path, 'r') as f:
            spec_dict = yaml.safe_load(f)
        _openapi_spec = OpenAPI.from_dict(spec_dict)
    return _openapi_spec

def validate_openapi_request(operation_id):
    """Decorator to validate incoming requests against OpenAPI spec."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                spec = get_openapi_spec()
                openapi_request = FlaskOpenAPIRequest(request)
                result = spec.unmarshal_request(openapi_request, operation_id)
                if result.errors:
                    abort(400, message=f"OpenAPI validation failed: {result.errors}")
                return f(*args, **kwargs)
            except Exception as e:
                # If OpenAPI validation fails, log but don't break existing functionality
                print(f"OpenAPI validation warning for {operation_id}: {e}")
                return f(*args, **kwargs)
        return wrapper
    return decorator

# Import all API resources
from .Watch import Watch, WatchHistory, WatchSingleHistory, CreateWatch, WatchFavicon
from .Tags import Tags, Tag
from .Import import Import
from .SystemInfo import SystemInfo
from .Notifications import Notifications
