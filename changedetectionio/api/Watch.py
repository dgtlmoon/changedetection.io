import os

from changedetectionio.validate_url import is_safe_valid_url

from flask_expects_json import expects_json
from changedetectionio import queuedWatchMetaData, strtobool
from changedetectionio import worker_handler
from flask_restful import abort, Resource
from flask import request, make_response, send_from_directory
from . import auth
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
        from copy import deepcopy
        watch = deepcopy(self.datastore.data['watching'].get(uuid))
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
            if not request.json.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400

        # Validate time_between_check when not using defaults
        validation_error = validate_time_between_check_required(request.json)
        if validation_error:
            return validation_error, 400

        # XSS etc protection
        if request.json.get('url') and not is_safe_valid_url(request.json.get('url')):
            return "Invalid URL", 400

        watch.update(request.json)

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

        if request.args.get('html'):
            content = watch.get_fetched_html(timestamp)
            if content:
                response = make_response(content, 200)
                response.mimetype = "text/html"
            else:
                response = make_response("No content found", 404)
                response.mimetype = "text/plain"
        else:
            content = watch.get_history_snapshot(timestamp)
            response = make_response(content, 200)
            response.mimetype = "text/plain"

        return response

class WatchHistoryDiff(Resource):
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

        # Get diff preferences (using defaults similar to the existing code)
        diff_prefs = {
            'diff_ignoreWhitespace': False,
            'diff_changesOnly': True
        }

        # Generate the diff
        content = diff.render_diff(
            previous_version_file_contents=from_version_file_contents,
            newest_version_file_contents=to_version_file_contents,
            ignore_junk=diff_prefs.get('diff_ignoreWhitespace'),
            include_equal=not diff_prefs.get('diff_changesOnly'),
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
            try:
                import magic
                mime = magic.from_file(
                    os.path.join(watch.watch_data_dir, favicon_filename),
                    mime=True
                )
            except ImportError:
                # Fallback, no python-magic
                import mimetypes
                mime, encoding = mimetypes.guess_type(favicon_filename)

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
            if not json_data.get('proxy') in plist:
                return "Invalid proxy choice, currently supported proxies are '{}'".format(', '.join(plist)), 400

        # Validate time_between_check when not using defaults
        validation_error = validate_time_between_check_required(json_data)
        if validation_error:
            return validation_error, 400

        extras = copy.deepcopy(json_data)

        # Because we renamed 'tag' to 'tags' but don't want to change the API (can do this in v2 of the API)
        tags = None
        if extras.get('tag'):
            tags = extras.get('tag')
            del extras['tag']

        del extras['url']

        new_uuid = self.datastore.add_watch(url=url, extras=extras, tag=tags)
        if new_uuid:
            worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': new_uuid}))
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
            for uuid in self.datastore.data['watching'].keys():
                worker_handler.queue_item_async_safe(self.update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
            return {'status': "OK"}, 200

        return list, 200