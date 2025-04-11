from flask import Blueprint, request, make_response
import random
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required

def construct_blueprint(datastore: ChangeDetectionStore):
    notification_blueprint = Blueprint('ui_notification', __name__, template_folder="../ui/templates")
    
    # AJAX endpoint for sending a test
    @notification_blueprint.route("/notification/send-test/<string:watch_uuid>", methods=['POST'])
    @notification_blueprint.route("/notification/send-test", methods=['POST'])
    @notification_blueprint.route("/notification/send-test/", methods=['POST'])
    @login_optionally_required
    def ajax_callback_send_notification_test(watch_uuid=None):

        # Watch_uuid could be unset in the case it`s used in tag editor, global settings
        import apprise
        from changedetectionio.notification.handler import process_notification
        from changedetectionio.notification.apprise_plugin.assets import apprise_asset

        from changedetectionio.notification.apprise_plugin.custom_handlers import apprise_http_custom_handler

        apobj = apprise.Apprise(asset=apprise_asset)

        is_global_settings_form = request.args.get('mode', '') == 'global-settings'
        is_group_settings_form = request.args.get('mode', '') == 'group-settings'

        # Use an existing random one on the global/main settings form
        if not watch_uuid and (is_global_settings_form or is_group_settings_form) \
                and datastore.data.get('watching'):
            logger.debug(f"Send test notification - Choosing random Watch {watch_uuid}")
            watch_uuid = random.choice(list(datastore.data['watching'].keys()))

        if not watch_uuid:
            return make_response("Error: You must have atleast one watch configured for 'test notification' to work", 400)

        watch = datastore.data['watching'].get(watch_uuid)

        notification_urls = None

        if request.form.get('notification_urls'):
            notification_urls = request.form['notification_urls'].strip().splitlines()

        if not notification_urls:
            logger.debug("Test notification - Trying by group/tag in the edit form if available")
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
            return 'Error: No Notification URLs set/found'

        for n_url in notification_urls:
            if len(n_url.strip()):
                if not apobj.add(n_url):
                    return f'Error:  {n_url} is not a valid AppRise URL.'

        try:
            # use the same as when it is triggered, but then override it with the form test values
            n_object = {
                'watch_url': request.form.get('window_url', "https://changedetection.io"),
                'notification_urls': notification_urls
            }

            # Only use if present, if not set in n_object it should use the default system value
            if 'notification_format' in request.form and request.form['notification_format'].strip():
                n_object['notification_format'] = request.form.get('notification_format', '').strip()

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
            sent_obj = process_notification(n_object, datastore)

        except Exception as e:
            e_str = str(e)
            # Remove this text which is not important and floods the container
            e_str = e_str.replace(
                "DEBUG - <class 'apprise.decorators.base.CustomNotifyPlugin.instantiate_plugin.<locals>.CustomNotifyPluginWrapper'>",
                '')

            return make_response(e_str, 400)

        return 'OK - Sent test notifications'

    return notification_blueprint