"""
Schema utilities for Watch and Tag models.

Provides functions to extract readonly fields and properties from OpenAPI spec.
Shared by both the model layer and API layer to avoid circular dependencies.
"""

import functools


@functools.cache
def get_openapi_schema_dict():
    """
    Get the raw OpenAPI spec dictionary for schema access.

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
def get_readonly_watch_fields():
    """
    Extract readOnly field names from Watch schema in OpenAPI spec.

    Returns readOnly fields from WatchBase (uuid, date_created) + Watch-specific readOnly fields.

    Used by:
    - model/watch_base.py: Track when writable fields are edited
    - api/Watch.py: Filter readonly fields from PUT requests
    """
    return _resolve_readonly_fields('Watch')


@functools.cache
def get_readonly_tag_fields():
    """
    Extract readOnly field names from Tag schema in OpenAPI spec.

    Returns readOnly fields from WatchBase (uuid, date_created) + Tag-specific readOnly fields.
    """
    return _resolve_readonly_fields('Tag')
