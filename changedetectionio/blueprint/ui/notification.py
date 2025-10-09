from flask import Blueprint, request, make_response, jsonify
import random
from loguru import logger

from changedetectionio.notification.handler import process_notification
from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required

def construct_blueprint(datastore: ChangeDetectionStore):
    notification_blueprint = Blueprint('ui_notification', __name__, template_folder="../ui/templates")


    @notification_blueprint.route("/notification/render-preview/<string:watch_uuid>", methods=['POST'])
    @notification_blueprint.route("/notification/render-preview", methods=['POST'])
    @notification_blueprint.route("/notification/render-preview/", methods=['POST'])
    @login_optionally_required
    def ajax_callback_test_render_preview(watch_uuid=None):
        return ajax_callback_send_notification_test(watch_uuid=watch_uuid, send_as_null_test=True)

    # AJAX endpoint for sending a test
    @notification_blueprint.route("/notification/send-test/<string:watch_uuid>", methods=['POST'])
    @notification_blueprint.route("/notification/send-test", methods=['POST'])
    @notification_blueprint.route("/notification/send-test/", methods=['POST'])
    @login_optionally_required
    def ajax_callback_send_notification_test(watch_uuid=None, send_as_null_test=False):

        # Watch_uuid could be unset in the case it`s used in tag editor, global settings
        import apprise
        from urllib.parse import urlparse
        from changedetectionio.notification.apprise_plugin.assets import apprise_asset

        # Necessary so that we import our custom handlers
        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler, apprise_null_custom_handler

        apobj = apprise.Apprise(asset=apprise_asset)
        sent_obj = {}

        is_global_settings_form = request.args.get('mode', '') == 'global-settings'
        is_group_settings_form = request.args.get('mode', '') == 'group-settings'

        # Use an existing random one on the global/main settings form
        if not watch_uuid and is_global_settings_form and datastore.data.get('watching'):
            watch_uuid = random.choice(list(datastore.data['watching'].keys()))
            logger.debug(f"Send test notification - Chose random watch UUID: {watch_uuid}")

        if is_group_settings_form  and datastore.data.get('watching'):
            logger.debug(f"Send test notification - Choosing random Watch from group {watch_uuid}")
            matching_watches = [uuid for uuid, watch in datastore.data['watching'].items() if watch.get('tags') and watch_uuid in watch['tags']]
            if matching_watches:
                watch_uuid = random.choice(matching_watches)
            else:
                # Just fallback to any
                watch_uuid = random.choice(list(datastore.data['watching'].keys()))

        if not watch_uuid:
            return make_response("Error: You must have atleast one watch configured for 'test notification' to work", 400)

        watch = datastore.data['watching'].get(watch_uuid)

        notification_urls = []

        if send_as_null_test:
            test_schema = ''
            try:
                if request.form.get('notification_urls') and '://' in request.form.get('notification_urls'):
                    first_test_notification_url = request.form['notification_urls'].strip().splitlines()[0]
                    test_schema = urlparse(first_test_notification_url).scheme.lower().strip()
            except Exception as e:
                logger.error(f"Error trying to get a test schema based on the first notification_url {str(e)}")

            notification_urls = [
                # Null lets us do the whole chain of the same code without any extra repeated code
                f'null://null-test-just-to-render-everything-on-the-same-codepath-and-get-preview?test_schema={test_schema}'
            ]

        else:
            if request.form.get('notification_urls'):
                notification_urls += request.form['notification_urls'].strip().splitlines()

        if not notification_urls:
            logger.debug("Test notification - Trying by group/tag in the edit form if available")
            # @todo this logic is not clear, omegaconf?
            # On an edit page, we should also fire off to the tags if they have notifications
            if request.form.get('tags') and request.form['tags'].strip():
                for k in request.form['tags'].split(','):
                    tag = datastore.tag_exists_by_name(k.strip())
                    notification_urls = tag.get('notifications_urls') if tag and tag.get('notifications_urls') else None

        if not notification_urls and not is_global_settings_form and not is_group_settings_form:
            # In the global settings, use only what is typed currently in the text box
            logger.debug("Test notification - Trying by global system settings notifications")
            if datastore.data['settings']['application'].get('notification_urls'):
                notification_urls = datastore.data['settings']['application']['notification_urls']

        if not notification_urls:
            return make_response("Error: No Notification URLs set/found.", 400)

        for n_url in notification_urls:
            if len(n_url.strip()):
                if not apobj.add(n_url):
                    return make_response(f'Error: {n_url} is not a valid AppRise URL.', 400)

        try:
            # use the same as when it is triggered, but then override it with the form test values
            n_object = {
                'watch_url': request.form.get('window_url', "https://changedetection.io"),
                'notification_urls': notification_urls,
                'uuid': watch_uuid  # Ensure uuid is present so diff rendering works
            }

            # Only use if present, if not set in n_object it should use the default system value
            notif_format = request.form.get('notification_format', '').strip()
            # Use it if provided and not "System default", otherwise fall back
            if notif_format and notif_format != 'System default':
                n_object['notification_format'] = notif_format
            else:
                n_object['notification_format'] = datastore.data['settings']['application'].get('notification_format')

            if 'notification_title' in request.form and request.form['notification_title'].strip():
                n_object['notification_title'] = request.form.get('notification_title', '').strip()
            elif datastore.data['settings']['application'].get('notification_title'):
                n_object['notification_title'] = datastore.data['settings']['application'].get('notification_title')
            else:
                n_object['notification_title'] = "Test title"

            if 'notification_body' in request.form and request.form['notification_body'].strip():
                n_object['notification_body'] = request.form.get('notification_body', '').strip()
            elif datastore.data['settings']['application'].get('notification_body'):
                n_object['notification_body'] = datastore.data['settings']['application'].get('notification_body')
            else:
                n_object['notification_body'] = "Test body"

            n_object['as_async'] = False
            n_object.update(watch.extra_notification_token_values())

            # This uses the same processor that the queue runner uses
            # @todo - Split the notification URLs so we know which one worked, maybe highlight them in green in the UI
            result = process_notification(n_object, datastore)
            if result:
                sent_obj['result'] = result[0]
                sent_obj['status'] = 'OK - Sent test notifications'

        except Exception as e:
            e_str = str(e)
            # Remove this text which is not important and floods the container
            e_str = e_str.replace(
                "DEBUG - <class 'apprise.decorators.base.CustomNotifyPlugin.instantiate_plugin.<locals>.CustomNotifyPluginWrapper'>",
                '')
            return make_response(e_str, 400)

        # it will be a list of things reached, for this purpose just the first is good so we can see the body that was sent
        return make_response(sent_obj, 200)

    return notification_blueprint