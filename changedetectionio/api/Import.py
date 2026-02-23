from changedetectionio.strtobool import strtobool
from flask_restful import abort, Resource
from flask import request
from functools import wraps
from . import auth, validate_openapi_request
from ..validate_url import is_safe_valid_url
import json

# Number of URLs above which import switches to background processing
IMPORT_SWITCH_TO_BACKGROUND_THRESHOLD = 20


def default_content_type(content_type='text/plain'):
    """Decorator to set a default Content-Type header if none is provided."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.content_type:
                # Set default content type in the request environment
                request.environ['CONTENT_TYPE'] = content_type
            return f(*args, **kwargs)
        return wrapper
    return decorator


def convert_query_param_to_type(value, schema_property):
    """
    Convert a query parameter string to the appropriate type based on schema definition.

    Args:
        value: String value from query parameter
        schema_property: Schema property definition with 'type' or 'anyOf' field

    Returns:
        Converted value in the appropriate type

    Supports both OpenAPI 3.1 formats:
    - type: [string, 'null']  (array format)
    - anyOf: [{type: string}, {type: null}]  (anyOf format)
    """
    prop_type = schema_property.get('type')

    # Handle OpenAPI 3.1 type arrays: type: [string, 'null']
    if isinstance(prop_type, list):
        # Use the first non-null type from the array
        for t in prop_type:
            if t != 'null':
                prop_type = t
                break
        else:
            prop_type = None

    # Handle anyOf schemas (older format)
    elif 'anyOf' in schema_property:
        # Use the first non-null type from anyOf
        for option in schema_property['anyOf']:
            if option.get('type') and option.get('type') != 'null':
                prop_type = option.get('type')
                break
        else:
            prop_type = None

    # Handle array type (e.g., notification_urls)
    if prop_type == 'array':
        # Support both comma-separated and JSON array format
        if value.startswith('['):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [v.strip() for v in value.split(',')]
        return [v.strip() for v in value.split(',')]

    # Handle object type (e.g., time_between_check, headers)
    elif prop_type == 'object':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON object for field: {value}")

    # Handle boolean type
    elif prop_type == 'boolean':
        return strtobool(value)

    # Handle integer type
    elif prop_type == 'integer':
        return int(value)

    # Handle number type (float)
    elif prop_type == 'number':
        return float(value)

    # Default: return as string
    return value


class Import(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @default_content_type('text/plain') #3547 #3542
    @validate_openapi_request('importWatches')
    def post(self):
        """Import a list of watched URLs with optional watch configuration."""
        from . import get_watch_schema_properties
        # Special parameters that are NOT watch configuration
        special_params = {'tag', 'tag_uuids', 'dedupe', 'proxy'}

        extras = {}

        # Handle special 'proxy' parameter
        if request.args.get('proxy'):
            plist = self.datastore.proxy_list
            if not request.args.get('proxy') in plist:
                proxy_list_str = ', '.join(plist) if plist else 'none configured'
                return f"Invalid proxy choice, currently supported proxies are '{proxy_list_str}'", 400
            else:
                extras['proxy'] = request.args.get('proxy')

        # Handle special 'dedupe' parameter
        dedupe = strtobool(request.args.get('dedupe', 'true'))

        # Handle special 'tag' and 'tag_uuids' parameters
        tags = request.args.get('tag')
        tag_uuids = request.args.get('tag_uuids')

        if tag_uuids:
            tag_uuids = tag_uuids.split(',')

        # Extract ALL other query parameters as watch configuration
        # Get schema from OpenAPI spec (replaces old schema_create_watch)
        schema_properties = get_watch_schema_properties()
        for param_name, param_value in request.args.items():
            # Skip special parameters
            if param_name in special_params:
                continue

            # Skip if not in schema (unknown parameter)
            if param_name not in schema_properties:
                return f"Unknown watch configuration parameter: {param_name}", 400

            # Convert to appropriate type based on schema
            try:
                converted_value = convert_query_param_to_type(param_value, schema_properties[param_name])
                extras[param_name] = converted_value
            except (ValueError, json.JSONDecodeError) as e:
                return f"Invalid value for parameter '{param_name}': {str(e)}", 400

        # Validate processor if provided
        if 'processor' in extras:
            from changedetectionio.processors import available_processors
            available = [p[0] for p in available_processors()]
            if extras['processor'] not in available:
                return f"Invalid processor '{extras['processor']}'. Available processors: {', '.join(available)}", 400

        # Validate fetch_backend if provided
        if 'fetch_backend' in extras:
            from changedetectionio.content_fetchers import available_fetchers
            available = [f[0] for f in available_fetchers()]
            # Also allow 'system' and extra_browser_* patterns
            is_valid = (
                extras['fetch_backend'] == 'system' or
                extras['fetch_backend'] in available or
                extras['fetch_backend'].startswith('extra_browser_')
            )
            if not is_valid:
                return f"Invalid fetch_backend '{extras['fetch_backend']}'. Available: system, {', '.join(available)}", 400

        # Validate notification_urls if provided
        if 'notification_urls' in extras:
            from wtforms import ValidationError
            from changedetectionio.api.Notifications import validate_notification_urls
            try:
                validate_notification_urls(extras['notification_urls'])
            except ValidationError as e:
                return f"Invalid notification_urls: {str(e)}", 400

        urls = request.get_data().decode('utf8').splitlines()
        # Clean and validate URLs upfront
        urls_to_import = []
        for url in urls:
            url = url.strip()
            if not len(url):
                continue

            # Validate URL
            if not is_safe_valid_url(url):
                return f"Invalid or unsupported URL - {url}", 400

            # Check for duplicates if dedupe is enabled
            if dedupe and self.datastore.url_exists(url):
                continue

            urls_to_import.append(url)

        # For small imports, process synchronously for immediate feedback
        if len(urls_to_import) < IMPORT_SWITCH_TO_BACKGROUND_THRESHOLD:
            added = []
            for url in urls_to_import:
                new_uuid = self.datastore.add_watch(url=url, extras=extras, tag=tags, tag_uuids=tag_uuids)
                added.append(new_uuid)
            return added, 200

        # For large imports (>= 20), process in background thread
        else:
            import threading
            from loguru import logger

            def import_watches_background():
                """Background thread to import watches - discarded after completion."""
                try:
                    added_count = 0
                    for url in urls_to_import:
                        try:
                            self.datastore.add_watch(url=url, extras=extras, tag=tags, tag_uuids=tag_uuids)
                            added_count += 1
                        except Exception as e:
                            logger.error(f"Error importing URL {url}: {e}")

                    logger.info(f"Background import complete: {added_count} watches created")
                except Exception as e:
                    logger.error(f"Error in background import: {e}")

            # Start background thread and return immediately
            thread = threading.Thread(target=import_watches_background, daemon=True, name="ImportWatches-Background")
            thread.start()

            return {'status': f'Importing {len(urls_to_import)} URLs in background', 'count': len(urls_to_import)}, 202