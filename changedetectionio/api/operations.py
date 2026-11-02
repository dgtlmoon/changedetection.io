"""
Watch and tag operations shared by the REST API and the MCP server, so both validate the same way and give the
same answers. Each raises ApiError(message, status) with the REST API's message and HTTP status.
"""
import copy

from loguru import logger


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


# {schema_name: (the merged spec dict it was built from, validator)}
_spec_validators = {}


def _spec_validator(schema_name):
    """A JSON Schema validator for one of the API spec's component schemas (CreateWatch, UpdateWatch...).

    Loaded on first use, not at startup, and from the merged spec, so plugin processors and fields are included.
    Rebuilt whenever the merged spec is (its cache is cleared when plugins change, e.g. in tests), so it never
    holds on to an older spec.
    """
    from openapi_schema_validator import OAS31Validator
    from changedetectionio.api import get_openapi_schema_dict
    spec = get_openapi_schema_dict()
    cached = _spec_validators.get(schema_name)
    if cached and cached[0] is spec:
        return cached[1]
    root = dict(spec)
    # Validate against the component, resolving its $refs inside the whole spec document
    root['$ref'] = f'#/components/schemas/{schema_name}'
    validator = OAS31Validator(root)
    _spec_validators[schema_name] = (spec, validator)
    return validator


def validate_against_spec(data, schema_name):
    """Check values (types, lengths, list sizes, enums, patterns) against the API spec. Raises ApiError listing them.

    The REST API also checks request bodies with openapi-core; doing it here means every way into a watch
    (REST, MCP, anything later) gets the same checks.
    """
    errors = sorted(_spec_validator(schema_name).iter_errors(data), key=lambda e: [str(p) for p in e.path])
    if errors:
        raise ApiError('; '.join(spec_error_message(e) for e in errors[:10]))


def spec_error_message(error):
    """A short message for a jsonschema error, without repeating the (possibly huge) value it was about."""
    where = '.'.join(str(p) for p in error.path) or 'body'
    kind, limit = error.validator, error.validator_value
    short = None
    if kind in ('maxLength', 'minLength'):
        short = f"{'longer' if kind == 'maxLength' else 'shorter'} than {limit} characters"
    elif kind in ('maxItems', 'minItems'):
        short = f"{'more' if kind == 'maxItems' else 'fewer'} than {limit} items"
    elif kind in ('maximum', 'minimum'):
        short = f"{'more' if kind == 'maximum' else 'less'} than {limit}"
    elif kind == 'pattern':
        short = f"doesn't match the pattern {limit}"
    elif kind == 'enum':
        short = f"must be one of {', '.join(map(str, limit))}"
    elif kind == 'type':
        short = f"must be of type {limit if isinstance(limit, str) else ' or '.join(limit)}"
    message = short or error.message
    return f"{where}: {message[:300]}"


def _validate_common(datastore, data):
    """The checks create and update both run. Raises ApiError."""
    from changedetectionio.api.Watch import validate_jinja2_templates, validate_time_schedule_limit
    from changedetectionio.model.Watch import validate_time_between_check_required

    if data.get('proxy'):
        plist = datastore.proxy_list
        if not plist or data.get('proxy') not in plist:
            proxy_list_str = ', '.join(plist) if plist else 'none configured'
            raise ApiError(f"Invalid proxy choice, currently supported proxies are '{proxy_list_str}'")

    # Validate time_between_check when not using defaults
    error = validate_time_between_check_required(data)
    if error:
        raise ApiError(error)

    # An invalid timezone here makes the watch permanently unschedulable
    error = validate_time_schedule_limit(data)
    if error:
        raise ApiError(error)

    if 'notification_urls' in data:
        validate_notification_urls(data.get('notification_urls', []))

    error = validate_jinja2_templates(data)
    if error:
        raise ApiError(error)


def validate_notification_urls(notification_urls):
    """Raises ApiError when an Apprise URL isn't valid."""
    from wtforms import ValidationError
    from changedetectionio.api.Notifications import validate_notification_urls as validate
    try:
        validate(notification_urls)
    except ValidationError as e:
        raise ApiError(str(e))


def create_watch(datastore, data):
    """Create a watch from API-style JSON (`url` required, `tag` = comma separated tag names). Returns its uuid."""
    from changedetectionio import processors
    from changedetectionio.api import strip_internal_api_fields
    from changedetectionio.validate_url import is_safe_valid_url

    # Silently discard `__`-prefixed transient/internal keys (not part of the public schema).
    data = strip_internal_api_fields(data)
    url = (data.get('url') or '').strip()

    from changedetectionio.api.Watch import validate_jinja2_templates
    error = validate_jinja2_templates(data)
    if error:
        raise ApiError(error)

    if not is_safe_valid_url(url):
        raise ApiError("Invalid or unsupported URL")

    _validate_common(datastore, data)

    extras = copy.deepcopy(data)

    # Extract and remove processor config fields from extras
    processor_config_data = processors.extract_processor_config_from_form_data(extras)

    # Because we renamed 'tag' to 'tags' but don't want to change the API (can do this in v2 of the API)
    tags = None
    if extras.get('tag'):
        tags = extras.pop('tag')
    extras.pop('url', None)

    validate_against_spec(dict(extras, url=url), 'CreateWatch')

    # PAGE_WATCH_LIMIT - checked up front so a blocked add is reported as 429 rather than
    # being guessed at from add_watch() returning None
    if datastore.watch_limit_reached():
        current_watch_count = len(datastore.data['watching'])
        raise ApiError(f"Watch limit reached ({current_watch_count}/{datastore.watch_limit} watches). "
                       f"Cannot add more watches.", 429)

    new_uuid = datastore.add_watch(url=url, extras=extras, tag=tags)
    if not new_uuid:
        raise ApiError("Invalid or unsupported URL")

    # Save processor config to separate JSON file
    if processor_config_data:
        processors.save_processor_config(datastore, new_uuid, processor_config_data)
    return new_uuid


def update_watch(datastore, uuid, data):
    """Update a watch from API-style JSON. Raises ApiError, 404 when the watch doesn't exist."""
    from changedetectionio import processors
    from changedetectionio.api import (get_readonly_watch_fields, get_watch_schema_properties,
                                       strip_internal_api_fields, strip_readonly_processor_fields)
    from changedetectionio.model.Watch import model as WatchModel
    from changedetectionio.validate_url import is_safe_valid_url

    watch = datastore.data['watching'].get(uuid)
    if not watch:
        raise ApiError(f'No watch exists with the UUID of {uuid}', 404)
    data = data or {}

    _validate_common(datastore, data)

    # XSS etc protection - validate URL if it's being updated
    if 'url' in data:
        new_url = data.get('url')
        if new_url is None:
            raise ApiError("URL cannot be null")
        if not isinstance(new_url, str):
            raise ApiError("URL must be a string")
        if not new_url.strip():
            raise ApiError("URL cannot be empty or whitespace only")
        if not is_safe_valid_url(new_url.strip()):
            raise ApiError("Invalid or unsupported URL format. URL must use http://, https://, or ftp:// protocol")

    # Make a mutable copy for modification.
    # Silently discard `__`-prefixed transient/internal keys — they are not part of the
    # public schema and must never be writable (e.g. clients that round-trip GET → PUT).
    json_data = strip_internal_api_fields(dict(data))
    # Same for the read-only processor_state_* / processor_config_*_source fields GET adds
    json_data = strip_readonly_processor_fields(json_data)

    # Extract and remove processor config fields from json_data
    processor_config_data = processors.extract_processor_config_from_form_data(json_data)

    # Filter out readOnly fields (extracted from OpenAPI spec Watch schema), system-managed and never user-settable,
    # and @property attributes (computed/derived values from the model), which are not stored
    for field in get_readonly_watch_fields() | WatchModel.get_property_names():
        json_data.pop(field, None)

    validate_against_spec(json_data, 'UpdateWatch')

    # Validate remaining fields - reject truly unknown fields
    valid_fields = set(get_watch_schema_properties().keys())
    # Also allow last_viewed (explicitly defined in UpdateWatch schema)
    valid_fields.add('last_viewed')
    unknown_fields = set(json_data.keys()) - valid_fields
    if unknown_fields:
        raise ApiError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    watch.update(json_data)
    # The request alone can be valid but leave no interval once merged, e.g. nulling the
    # interval of a watch that already has time_between_check_use_default=False
    watch.ensure_valid_time_between_check()
    watch.commit()

    # Save processor config to JSON file
    processors.save_processor_config(datastore, uuid, processor_config_data)


def queue_rechecks(update_q, uuids):
    """Queue watches for a recheck without waiting for them. Skips ones already queued or running.

    Returns (queued, skipped). 20 or more are queued from a background thread so the request returns at once.
    """
    import threading
    from changedetectionio import queuedWatchMetaData, worker_pool

    busy = set(update_q.get_queued_uuids()) | set(worker_pool.get_running_uuids())
    to_queue = [u for u in uuids if u not in busy]

    def queue_all():
        for uuid in to_queue:
            worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

    if len(to_queue) < 20:
        queue_all()
    else:
        def background():
            try:
                queue_all()
                logger.info(f"Background queueing complete: {len(to_queue)} watches queued")
            except Exception as e:
                logger.error(f"Error in background queueing: {e}")
        threading.Thread(target=background, daemon=True, name="QueueRechecks").start()
    return len(to_queue), len(uuids) - len(to_queue)


def create_tag(datastore, data):
    """Create a tag/group from API-style JSON (`title` required). Returns its uuid (the existing one if the title exists)."""
    from changedetectionio.api import get_tag_schema_properties, strip_internal_api_fields
    from changedetectionio.api.Tags import validate_tag_colour

    data = strip_internal_api_fields(data or {})
    title = (data.get('title') or '').strip()

    unknown_fields = set(data.keys()) - set(get_tag_schema_properties().keys())
    if unknown_fields:
        raise ApiError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    colour_error = validate_tag_colour(data)
    if colour_error:
        raise ApiError(colour_error)

    new_uuid = datastore.add_tag(title=title)
    if not new_uuid:
        raise ApiError("Invalid or unsupported tag")

    # Apply any extra fields (e.g. processor_config_restock_diff) beyond just title
    extra = {k: v for k, v in data.items() if k != 'title'}
    if extra:
        tag = datastore.data['settings']['application']['tags'].get(new_uuid)
        if tag:
            tag.update(extra)
            tag.commit()
    return new_uuid


def update_tag(datastore, uuid, data):
    """Update a tag/group from API-style JSON. Raises ApiError, 404 when the tag doesn't exist."""
    from changedetectionio.api import get_readonly_tag_fields, get_tag_schema_properties, strip_internal_api_fields
    from changedetectionio.api.Tags import validate_tag_colour

    tag = datastore.data['settings']['application']['tags'].get(uuid)
    if not tag:
        raise ApiError(f'No tag exists with the UUID of {uuid}', 404)

    json_data = strip_internal_api_fields(dict(data or {}))
    if 'notification_urls' in json_data:
        validate_notification_urls(json_data.get('notification_urls', []))

    # Filter out readOnly fields (extracted from OpenAPI spec Tag schema), never user-settable
    for field in get_readonly_tag_fields():
        json_data.pop(field, None)

    unknown_fields = set(json_data.keys()) - set(get_tag_schema_properties().keys())
    if unknown_fields:
        raise ApiError(f"Unknown field(s): {', '.join(sorted(unknown_fields))}")

    colour_error = validate_tag_colour(json_data)
    if colour_error:
        raise ApiError(colour_error)

    tag.update(json_data)
    tag.commit()

    # Clear checksums for all watches using this tag to force reprocessing, tag changes affect inherited configuration
    cleared_count = datastore.clear_checksums_for_tag(uuid)
    logger.info(f"Tag {uuid} updated, cleared {cleared_count} watch checksums")


def delete_tag(datastore, uuid):
    """Delete a tag/group and remove it from every watch. Raises ApiError when it doesn't exist."""
    if not datastore.data['settings']['application']['tags'].get(uuid):
        raise ApiError(f'No tag exists with the UUID of {uuid}')

    del datastore.data['settings']['application']['tags'][uuid]
    for watch in datastore.data['watching'].values():
        if watch.get('tags') and uuid in watch['tags']:
            watch['tags'].remove(uuid)
            watch.commit()


def checking_now(datastore):
    """The watches the fetch workers are checking right now, longest running first (a stuck check comes first).

    [{'uuid', 'title', 'url', 'running_seconds'}], from the worker pool's in-memory state, so cheap to call.
    """
    import time
    from changedetectionio import worker_pool

    now = time.time()
    running = []
    for uuid in worker_pool.get_running_uuids():
        watch = datastore.data['watching'].get(uuid)
        started = worker_pool.get_uuid_started_at(uuid)
        running.append({'uuid': uuid, 'title': watch.label if watch else None, 'url': watch.get('url') if watch else None,
                        'running_seconds': round(now - started) if started else None})
    running.sort(key=lambda r: r['running_seconds'] or 0, reverse=True)
    return running
