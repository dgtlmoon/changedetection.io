import os
import threading

from changedetectionio.validate_url import is_safe_valid_url
from changedetectionio.favicon_utils import get_favicon_mime_type

from . import auth
from changedetectionio import queuedWatchMetaData, strtobool
from changedetectionio import worker_handler
from flask import request, make_response, send_from_directory
from flask_expects_json import expects_json
from flask_restful import abort, Resource
from loguru import logger
import copy

# Import schemas from __init__.py
from . import schema, schema_create_watch, schema_update_watch, validate_openapi_request
from ..notification import valid_notification_formats
from ..notification.handler import newline_re


def validate_time_between_check_required(json_data):
    """
    Validate that at least one time interval is specified when not using default settings.
    Returns None if valid, or error message string if invalid.
    Defaults to using global settings if time_between_check_use_default is not provided.
    """
    # Default to using global settings if not specified
    use_default = json_data.get('time_between_check_use_default', True)

    # If using default settings, no validation needed
    if use_default:
        return None

    # If not using defaults, check if time_between_check exists and has at least one non-zero value
    time_check = json_data.get('time_between_check')
    if not time_check:
        # No time_between_check provided and not using defaults - this is an error
        return "At least one time interval (weeks, days, hours, minutes, or seconds) must be specified when not using global settings."

    # time_between_check exists, check if it has at least one non-zero value
    if any([
        (time_check.get('weeks') or 0) > 0,
        (time_check.get('days') or 0) > 0,
        (time_check.get('hours') or 0) > 0,
        (time_check.get('minutes') or 0) > 0,
        (time_check.get('seconds') or 0) > 0
    ]):
        return None

    # time_between_check exists but all values are 0 or empty - this is an error
    return "At least one time interval (weeks, days, hours, minutes, or seconds) must be specified when not using global settings."


class Watch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    # Get information about a single watch, excluding the history list (can be large)
    # curl http://localhost:5000/api/v1/watch/<string:uuid>
    # @todo - version2 - ?muted and ?paused should be able to be called together, return the watch struct not "OK"
    # ?recheck=true
    @auth.check_token
    @validate_openapi_request('getWatch')
    def get(self, uuid):
        """Get information about a single watch, recheck, pause, or mute."""
        import time
        from copy import deepcopy
        watch = None
        # Retry up to 20 times if dict is being modified
        # With sleep(0), this is fast: ~200µs best case, ~20ms worst case under heavy load
        for attempt in range(20):
            try:
                watch = deepcopy(self.datastore.data['watching'].get(uuid))
                break
            except RuntimeError:
                # Dict changed during deepcopy, retry after yielding to scheduler
                # sleep(0) releases GIL and yields - no fixed delay, just lets other threads run
                if attempt < 19:  # Don't yield on last attempt
                    time.sleep(0)  # Yield to scheduler (microseconds, not milliseconds)

        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if request.args.get('recheck'):
            worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            return "OK", 200
        if request.args.get('paused', '') == 'paused':
            self.datastore.data['watching'].get(uuid).pause()
            return "OK", 200
        elif request.args.get('paused', '') == 'unpaused':
            self.datastore.data['watching'].get(uuid).unpause()
            return "OK", 200
        if request.args.get('muted', '') == 'muted':
            self.datastore.data['watching'].get(uuid).mute()
            return "OK", 200
        elif request.args.get('muted', '') == 'unmuted':
            self.datastore.data['watching'].get(uuid).unmute()
            return "OK", 200

        # Return without history, get that via another API call
        # Properties are not returned as a JSON, so add the required props manually
        watch['history_n'] = watch.history_n
        # attr .last_changed will check for the last written text snapshot on change
        watch['last_changed'] = watch.last_changed
        watch['viewed'] = watch.viewed
        watch['link'] = watch.link,

        return watch

    @auth.check_token
    @validate_openapi_request('deleteWatch')
    def delete(self, uuid):
        """Delete a watch and related history."""
        if not self.datastore.data['watching'].get(uuid):
            abort(400, message='No watch exists with the UUID of {}'.format(uuid))

        self.datastore.delete(uuid)
        return 'OK', 204

    @auth.check_token
    @validate_openapi_request('updateWatch')
    @expects_json(schema_update_watch)
    def put(self, uuid):
        """Update watch information."""
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))

        if request.json.get('proxy'):
            plist = self.datastore.proxy_list
            if not plist or request.json.get('proxy') not in plist:
                proxy_list_str = ', '.join(plist) if plist else 'none configured'
                return f"Invalid proxy choice, currently supported proxies are '{proxy_list_str}'", 400

        # Validate time_between_check when not using defaults
        validation_error = validate_time_between_check_required(request.json)
        if validation_error:
            return validation_error, 400

        # Validate notification_urls if provided
        if 'notification_urls' in request.json:
            from wtforms import ValidationError
            from changedetectionio.api.Notifications import validate_notification_urls
            try:
                notification_urls = request.json.get('notification_urls', [])
                if not isinstance(notification_urls, list):
                    return "notification_urls must be a list", 400
                validate_notification_urls(notification_urls)
            except ValidationError as e:
                return str(e), 400

        # XSS etc protection - validate URL if it's being updated
        if 'url' in request.json:
            new_url = request.json.get('url')

            # URL must be a non-empty string
            if new_url is None:
                return "URL cannot be null", 400

            if not isinstance(new_url, str):
                return "URL must be a string", 400

            if not new_url.strip():
                return "URL cannot be empty or whitespace only", 400

            if not is_safe_valid_url(new_url.strip()):
                return "Invalid or unsupported URL format. URL must use http://, https://, or ftp:// protocol", 400

        # Handle processor-config-* fields separately (save to JSON, not datastore)
        from changedetectionio import processors
        processor_config_data = {}
        regular_data = {}

        for key, value in request.json.items():
            if key.startswith('processor_config_'):
                config_key = key.replace('processor_config_', '')
                if value:  # Only save non-empty values
                    processor_config_data[config_key] = value
            else:
                regular_data[key] = value

        # Update watch with regular (non-processor-config) fields
        watch.update(regular_data)

        # Save processor config to JSON file if any config data exists
        if processor_config_data:
            try:
                processor_name = request.json.get('processor', watch.get('processor'))
                if processor_name:
                    # Create a processor instance to access config methods
                    from changedetectionio.processors import difference_detection_processor
                    processor_instance = difference_detection_processor(self.datastore, uuid)
                    # Use processor name as filename so each processor keeps its own config
                    config_filename = f'{processor_name}.json'
                    processor_instance.update_extra_watch_config(config_filename, processor_config_data)
                    logger.debug(f"API: Saved processor config to {config_filename}: {processor_config_data}")

                    # Call optional edit_hook if processor has one
                    try:
                        import importlib
                        edit_hook_module_name = f'changedetectionio.processors.{processor_name}.edit_hook'

                        try:
                            edit_hook = importlib.import_module(edit_hook_module_name)
                            logger.debug(f"API: Found edit_hook module for {processor_name}")

                            if hasattr(edit_hook, 'on_config_save'):
                                logger.info(f"API: Calling edit_hook.on_config_save for {processor_name}")
                                # Call hook and get updated config
                                updated_config = edit_hook.on_config_save(watch, processor_config_data, self.datastore)
                                # Save updated config back to file
                                processor_instance.update_extra_watch_config(config_filename, updated_config)
                                logger.info(f"API: Edit hook updated config: {updated_config}")
                            else:
                                logger.debug(f"API: Edit hook module found but no on_config_save function")
                        except ModuleNotFoundError:
                            logger.debug(f"API: No edit_hook module for processor {processor_name} (this is normal)")
                    except Exception as hook_error:
                        logger.error(f"API: Edit hook error (non-fatal): {hook_error}", exc_info=True)

            except Exception as e:
                logger.error(f"API: Failed to save processor config: {e}")

        return "OK", 200


class WatchHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    # Get a list of available history for a watch by UUID
    # curl http://localhost:5000/api/v1/watch/<string:uuid>/history
    @auth.check_token
    @validate_openapi_request('getWatchHistory')
    def get(self, uuid):
        """Get a list of all historical snapshots available for a watch."""
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message='No watch exists with the UUID of {}'.format(uuid))
        return watch.history, 200


class WatchSingleHistory(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('getWatchSnapshot')
    def get(self, uuid, timestamp):
        """Get single snapshot from watch."""
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f"No watch exists with the UUID of {uuid}")

        if not len(watch.history):
            abort(404, message=f"Watch found but no history exists for the UUID {uuid}")

        if timestamp == 'latest':
            timestamp = list(watch.history.keys())[-1]

        # Validate that the timestamp exists in history
        if timestamp not in watch.history:
            abort(404, message=f"No history snapshot found for timestamp '{timestamp}'")

        if request.args.get('html'):
            content = watch.get_fetched_html(timestamp)
            if content:
                response = make_response(content, 200)
                response.mimetype = "text/html"
            else:
                response = make_response("No content found", 404)
                response.mimetype = "text/plain"
        else:
            content = watch.get_history_snapshot(timestamp=timestamp)
            response = make_response(content, 200)
            response.mimetype = "text/plain"

        return response

class WatchHistoryDiff(Resource):
    """
    Generate diff between two historical snapshots.

    Note: This API endpoint currently returns text-based diffs and works best
    with the text_json_diff processor. Future processor types (like image_diff,
    restock_diff) may want to implement their own specialized API endpoints
    for returning processor-specific data (e.g., price charts, image comparisons).

    The web UI diff page (/diff/<uuid>) is processor-aware and delegates rendering
    to processors/{type}/difference.py::render() for processor-specific visualizations.
    """
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('getWatchHistoryDiff')
    def get(self, uuid, from_timestamp, to_timestamp):
        """Generate diff between two historical snapshots."""
        from changedetectionio import diff
        from changedetectionio.notification.handler import apply_service_tweaks

        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f"No watch exists with the UUID of {uuid}")

        if not len(watch.history):
            abort(404, message=f"Watch found but no history exists for the UUID {uuid}")

        history_keys = list(watch.history.keys())

        # Handle 'latest' keyword for to_timestamp
        if to_timestamp == 'latest':
            to_timestamp = history_keys[-1]

        # Handle 'previous' keyword for from_timestamp (second-most-recent)
        if from_timestamp == 'previous':
            if len(history_keys) < 2:
                abort(404, message=f"Not enough history entries. Need at least 2 snapshots for 'previous'")
            from_timestamp = history_keys[-2]

        # Validate timestamps exist
        if from_timestamp not in watch.history:
            abort(404, message=f"From timestamp {from_timestamp} not found in watch history")
        if to_timestamp not in watch.history:
            abort(404, message=f"To timestamp {to_timestamp} not found in watch history")

        # Get the format parameter (default to 'text')
        output_format = request.args.get('format', 'text').lower()

        # Validate format
        if output_format not in valid_notification_formats.keys():
            abort(400, message=f"Invalid format. Must be one of: {', '.join(valid_notification_formats.keys())}")

        # Get the word_diff parameter (default to False - line-level mode)
        word_diff = strtobool(request.args.get('word_diff', 'false'))

        # Get the no_markup parameter (default to False)
        no_markup = strtobool(request.args.get('no_markup', 'false'))

        # Retrieve snapshot contents
        from_version_file_contents = watch.get_history_snapshot(from_timestamp)
        to_version_file_contents = watch.get_history_snapshot(to_timestamp)

        # Get diff preferences from query parameters (matching UI preferences in DIFF_PREFERENCES_CONFIG)
        # Support both 'type' (UI parameter) and 'word_diff' (API parameter) for backward compatibility
        diff_type = request.args.get('type', 'diffLines')
        if diff_type == 'diffWords':
            word_diff = True

        # Get boolean diff preferences with defaults from DIFF_PREFERENCES_CONFIG
        changes_only = strtobool(request.args.get('changesOnly', 'true'))
        ignore_whitespace = strtobool(request.args.get('ignoreWhitespace', 'false'))
        include_removed = strtobool(request.args.get('removed', 'true'))
        include_added = strtobool(request.args.get('added', 'true'))
        include_replaced = strtobool(request.args.get('replaced', 'true'))

        # Generate the diff with all preferences
        content = diff.render_diff(
            previous_version_file_contents=from_version_file_contents,
            newest_version_file_contents=to_version_file_contents,
            ignore_junk=ignore_whitespace,
            include_equal=changes_only,
            include_removed=include_removed,
            include_added=include_added,
            include_replaced=include_replaced,
            word_diff=word_diff,
        )

        # Skip formatting if no_markup is set
        if no_markup:
            mimetype = "text/plain"
        else:
            # Apply formatting based on the requested format
            if output_format == 'htmlcolor':
                from changedetectionio.notification.handler import apply_html_color_to_body
                content = apply_html_color_to_body(n_body=content)
                mimetype = "text/html"
            else:
                # Apply service tweaks for text/html formats
                # Pass empty URL and title as they're not used for the placeholder replacement we need
                _, content, _ = apply_service_tweaks(
                    url='',
                    n_body=content,
                    n_title='',
                    requested_output_format=output_format
                )
                mimetype = "text/html" if output_format == 'html' else "text/plain"

            if 'html' in output_format:
                content = newline_re.sub('<br>\r\n', content)

        response = make_response(content, 200)
        response.mimetype = mimetype
        return response


class WatchFavicon(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    @auth.check_token
    @validate_openapi_request('getWatchFavicon')
    def get(self, uuid):
        """Get favicon for a watch."""
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f"No watch exists with the UUID of {uuid}")

        favicon_filename = watch.get_favicon_filename()
        if favicon_filename:
            # Use cached MIME type detection
            filepath = os.path.join(watch.watch_data_dir, favicon_filename)
            mime = get_favicon_mime_type(filepath)

            response = make_response(send_from_directory(watch.watch_data_dir, favicon_filename))
            response.headers['Content-type'] = mime
            response.headers['Cache-Control'] = 'max-age=300, must-revalidate'  # Cache for 5 minutes, then revalidate
            return response

        abort(404, message=f'No Favicon available for {uuid}')


class CreateWatch(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    @auth.check_token
    @validate_openapi_request('createWatch')
    @expects_json(schema_create_watch)
    def post(self):
        """Create a single watch."""

        json_data = request.get_json()
        url = json_data['url'].strip()

        if not is_safe_valid_url(url):
            return "Invalid or unsupported URL", 400

        if json_data.get('proxy'):
            plist = self.datastore.proxy_list
            if not plist or json_data.get('proxy') not in plist:
                proxy_list_str = ', '.join(plist) if plist else 'none configured'
                return f"Invalid proxy choice, currently supported proxies are '{proxy_list_str}'", 400

        # Validate time_between_check when not using defaults
        validation_error = validate_time_between_check_required(json_data)
        if validation_error:
            return validation_error, 400

        # Validate notification_urls if provided
        if 'notification_urls' in json_data:
            from wtforms import ValidationError
            from changedetectionio.api.Notifications import validate_notification_urls
            try:
                notification_urls = json_data.get('notification_urls', [])
                if not isinstance(notification_urls, list):
                    return "notification_urls must be a list", 400
                validate_notification_urls(notification_urls)
            except ValidationError as e:
                return str(e), 400

        extras = copy.deepcopy(json_data)

        # Because we renamed 'tag' to 'tags' but don't want to change the API (can do this in v2 of the API)
        tags = None
        if extras.get('tag'):
            tags = extras.get('tag')
            del extras['tag']

        del extras['url']

        new_uuid = self.datastore.add_watch(url=url, extras=extras, tag=tags)
        if new_uuid:
# Dont queue because the scheduler will check that it hasnt been checked before anyway
#            worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
            return {'uuid': new_uuid}, 201
        else:
            return "Invalid or unsupported URL", 400

    @auth.check_token
    @validate_openapi_request('listWatches')
    def get(self):
        """List watches."""
        list = {}

        tag_limit = request.args.get('tag', '').lower()
        for uuid, watch in self.datastore.data['watching'].items():
            # Watch tags by name (replace the other calls?)
            tags = self.datastore.get_all_tags_for_watch(uuid=uuid)
            if tag_limit and not any(v.get('title').lower() == tag_limit for k, v in tags.items()):
                continue

            list[uuid] = {
                'last_changed': watch.last_changed,
                'last_checked': watch['last_checked'],
                'last_error': watch['last_error'],
                'link': watch.link,
                'page_title': watch['page_title'],
                'title': watch['title'],
                'url': watch['url'],
                'viewed': watch.viewed
            }

        if request.args.get('recheck_all'):
            # Collect all watches to queue
            watches_to_queue = self.datastore.data['watching'].keys()

            # If less than 20 watches, queue synchronously for immediate feedback
            if len(watches_to_queue) < 20:
                # Get already queued/running UUIDs once (efficient)
                queued_uuids = set(self.update_q.get_queued_uuids())
                running_uuids = set(worker_handler.get_running_uuids())

                # Filter out watches that are already queued or running
                watches_to_queue_filtered = [
                    uuid for uuid in watches_to_queue
                    if uuid not in queued_uuids and uuid not in running_uuids
                ]

                # Queue only the filtered watches
                for uuid in watches_to_queue_filtered:
                    worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))

                # Provide feedback about skipped watches
                skipped_count = len(watches_to_queue) - len(watches_to_queue_filtered)
                if skipped_count > 0:
                    return {'status': f'OK, queued {len(watches_to_queue_filtered)} watches for rechecking ({skipped_count} already queued or running)'}, 200
                else:
                    return {'status': f'OK, queued {len(watches_to_queue_filtered)} watches for rechecking'}, 200
            else:
                # 20+ watches - queue in background thread to avoid blocking API response
                # Capture queued/running state before background thread
                queued_uuids = set(self.update_q.get_queued_uuids())
                running_uuids = set(worker_handler.get_running_uuids())

                def queue_all_watches_background():
                    """Background thread to queue all watches - discarded after completion."""
                    try:
                        queued_count = 0
                        skipped_count = 0
                        for uuid in watches_to_queue:
                            # Check if already queued or running (state captured at start)
                            if uuid not in queued_uuids and uuid not in running_uuids:
                                worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
                                queued_count += 1
                            else:
                                skipped_count += 1

                        logger.info(f"Background queueing complete: {queued_count} watches queued, {skipped_count} skipped (already queued/running)")
                    except Exception as e:
                        logger.error(f"Error in background queueing all watches: {e}")

                # Start background thread and return immediately
                thread = threading.Thread(target=queue_all_watches_background, daemon=True, name="QueueAllWatches-Background")
                thread.start()

                return {'status': f'OK, queueing {len(watches_to_queue)} watches in background'}, 202

        return list, 200