import copy
import functools
from flask import request, abort
from loguru import logger
from . import api_schema
from ..model import watch_base

# Build a JSON Schema atleast partially based on our Watch model
watch_base_config = watch_base()
schema = api_schema.build_watch_json_schema(watch_base_config)

schema_create_watch = copy.deepcopy(schema)
schema_create_watch['required'] = ['url']
del schema_create_watch['properties']['last_viewed']
# Allow processor_config_* fields (handled separately in endpoint)
schema_create_watch['patternProperties'] = {
    '^processor_config_': {'type': ['string', 'number', 'boolean', 'object', 'array', 'null']}
}

schema_update_watch = copy.deepcopy(schema)
schema_update_watch['additionalProperties'] = False
# Allow processor_config_* fields (handled separately in endpoint)
schema_update_watch['patternProperties'] = {
    '^processor_config_': {'type': ['string', 'number', 'boolean', 'object', 'array', 'null']}
}

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

@functools.cache
def get_openapi_spec():
    """Lazy load OpenAPI spec and dependencies only when validation is needed."""
    import os
    import yaml  # Lazy import - only loaded when API validation is actually used
    from openapi_core import OpenAPI  # Lazy import - saves ~10.7 MB on startup

    spec_path = os.path.join(os.path.dirname(__file__), '../../docs/api-spec.yaml')
    if not os.path.exists(spec_path):
        # Possibly for pip3 packages
        spec_path = os.path.join(os.path.dirname(__file__), '../docs/api-spec.yaml')

    with open(spec_path, 'r', encoding='utf-8') as f:
        spec_dict = yaml.safe_load(f)
    _openapi_spec = OpenAPI.from_dict(spec_dict)
    return _openapi_spec

def validate_openapi_request(operation_id):
    """Decorator to validate incoming requests against OpenAPI spec."""
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            from werkzeug.exceptions import BadRequest
            try:
                # Skip OpenAPI validation for GET requests since they don't have request bodies
                if request.method.upper() != 'GET':
                    # Lazy import - only loaded when actually validating a request
                    from openapi_core.contrib.flask import FlaskOpenAPIRequest

                    spec = get_openapi_spec()
                    openapi_request = FlaskOpenAPIRequest(request)
                    result = spec.unmarshal_request(openapi_request)
                    if result.errors:
                        error_details = []
                        for error in result.errors:
                            # Extract detailed schema errors from __cause__
                            if hasattr(error, '__cause__') and hasattr(error.__cause__, 'schema_errors'):
                                for schema_error in error.__cause__.schema_errors:
                                    field = '.'.join(str(p) for p in schema_error.path) if schema_error.path else 'body'
                                    msg = schema_error.message if hasattr(schema_error, 'message') else str(schema_error)
                                    error_details.append(f"{field}: {msg}")
                            else:
                                error_details.append(str(error))
                            logger.error(f"API Call - Validation failed: {'; '.join(error_details)}")
                        raise BadRequest(f"Validation failed: {'; '.join(error_details)}")
            except BadRequest:
                # Re-raise BadRequest exceptions (validation failures)
                raise
            except Exception as e:
                # If OpenAPI spec loading fails, log but don't break existing functionality
                logger.critical(f"OpenAPI validation warning for {operation_id}: {e}")
                abort(500)
            return f(*args, **kwargs)
        return wrapper
    return decorator

# Import all API resources
from .Watch import Watch, WatchHistory, WatchSingleHistory, WatchHistoryDiff, CreateWatch, WatchFavicon
from .Tags import Tags, Tag
from .Import import Import
from .SystemInfo import SystemInfo
from .Notifications import Notifications

