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

@functools.cache
def _resolve_schema_properties(schema_name):
    """
    Generic helper to resolve schema properties, including allOf inheritance.

    Args:
        schema_name: Name of the schema (e.g., 'WatchBase', 'Watch', 'Tag')

    Returns:
        dict: All properties including inherited ones from $ref schemas
    """
    spec_dict = get_openapi_schema_dict()
    schema = spec_dict['components']['schemas'].get(schema_name, {})

    properties = {}

    # Handle allOf (schema inheritance)
    if 'allOf' in schema:
        for item in schema['allOf']:
            # Resolve $ref to parent schema
            if '$ref' in item:
                ref_path = item['$ref'].split('/')[-1]
                ref_schema = spec_dict['components']['schemas'].get(ref_path, {})
                properties.update(ref_schema.get('properties', {}))
            # Add schema-specific properties
            if 'properties' in item:
                properties.update(item['properties'])
    else:
        # Direct properties (no inheritance)
        properties = schema.get('properties', {})

    return properties

@functools.cache
def _resolve_readonly_fields(schema_name):
    """
    Generic helper to resolve readOnly fields, including allOf inheritance.

    Args:
        schema_name: Name of the schema (e.g., 'Watch', 'Tag')

    Returns:
        frozenset: All readOnly field names including inherited ones
    """
    spec_dict = get_openapi_schema_dict()
    schema = spec_dict['components']['schemas'].get(schema_name, {})

    readonly_fields = set()

    # Handle allOf (schema inheritance)
    if 'allOf' in schema:
        for item in schema['allOf']:
            # Resolve $ref to parent schema
            if '$ref' in item:
                ref_path = item['$ref'].split('/')[-1]
                ref_schema = spec_dict['components']['schemas'].get(ref_path, {})
                if 'properties' in ref_schema:
                    for field_name, field_def in ref_schema['properties'].items():
                        if field_def.get('readOnly') is True:
                            readonly_fields.add(field_name)
            # Check schema-specific properties
            if 'properties' in item:
                for field_name, field_def in item['properties'].items():
                    if field_def.get('readOnly') is True:
                        readonly_fields.add(field_name)
    else:
        # Direct properties (no inheritance)
        if 'properties' in schema:
            for field_name, field_def in schema['properties'].items():
                if field_def.get('readOnly') is True:
                    readonly_fields.add(field_name)

    return frozenset(readonly_fields)

@functools.cache
def get_watch_schema_properties():
    """
    Extract watch schema properties from OpenAPI spec for Import endpoint.

    Returns WatchBase properties (all writable Watch fields).
    """
    return _resolve_schema_properties('WatchBase')

@functools.cache
def get_readonly_watch_fields():
    """
    Extract readOnly field names from Watch schema in OpenAPI spec.

    Returns readOnly fields from WatchBase (uuid, date_created) + Watch-specific readOnly fields.
    """
    return _resolve_readonly_fields('Watch')

@functools.cache
def get_tag_schema_properties():
    """
    Extract Tag schema properties from OpenAPI spec.

    Returns WatchBase properties + Tag-specific properties (overrides_watch).
    """
    return _resolve_schema_properties('Tag')

@functools.cache
def get_readonly_tag_fields():
    """
    Extract readOnly field names from Tag schema in OpenAPI spec.

    Returns readOnly fields from WatchBase (uuid, date_created) + Tag-specific readOnly fields.
    """
    return _resolve_readonly_fields('Tag')

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

