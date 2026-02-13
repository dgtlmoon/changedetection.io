import functools
from flask import request, abort
from loguru import logger

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

@functools.cache
def get_openapi_schema_dict():
    """
    Get the raw OpenAPI spec dictionary for schema access.

    Used by Import endpoint to validate and convert query parameters.
    Returns the YAML dict directly (not the OpenAPI object).
    """
    import os
    import yaml

    spec_path = os.path.join(os.path.dirname(__file__), '../../docs/api-spec.yaml')
    if not os.path.exists(spec_path):
        spec_path = os.path.join(os.path.dirname(__file__), '../docs/api-spec.yaml')

    with open(spec_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def get_watch_schema_properties():
    """
    Extract watch schema properties from OpenAPI spec for Import endpoint.

    Returns a dict of property names to their schema definitions,
    suitable for validating query parameters.
    """
    spec_dict = get_openapi_schema_dict()

    # Get CreateWatch schema (which references WatchBase via allOf)
    create_watch_schema = spec_dict['components']['schemas']['CreateWatch']
    watch_base_schema = spec_dict['components']['schemas']['WatchBase']

    # Return WatchBase properties (CreateWatch uses allOf to extend it)
    return watch_base_schema.get('properties', {})

@functools.cache
def get_readonly_watch_fields():
    """
    Extract readOnly field names from Watch schema in OpenAPI spec.

    These are system-managed fields that should never be updated by user input.
    Used by the Watch PUT endpoint to filter out readOnly fields from requests.

    Returns:
        frozenset: Immutable set of field names marked as readOnly in the Watch schema
    """
    spec_dict = get_openapi_schema_dict()
    watch_schema = spec_dict['components']['schemas'].get('Watch', {})

    readonly_fields = set()

    # The Watch schema uses allOf to extend WatchBase and add readOnly properties
    if 'allOf' in watch_schema:
        for item in watch_schema['allOf']:
            # Look for the object that defines Watch-specific properties (not the $ref)
            if 'properties' in item:
                for field_name, field_def in item['properties'].items():
                    if field_def.get('readOnly') is True:
                        readonly_fields.add(field_name)

    # Also check top-level properties (if schema structure changes)
    if 'properties' in watch_schema:
        for field_name, field_def in watch_schema['properties'].items():
            if field_def.get('readOnly') is True:
                readonly_fields.add(field_name)

    return frozenset(readonly_fields)

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

