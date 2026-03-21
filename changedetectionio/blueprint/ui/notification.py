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
        from changedetectionio.notification_service import NotificationContextData, set_basic_notification_vars
        import apprise
        from changedetectionio.notification.handler import process_notification
        from changedetectionio.notification.apprise_plugin.assets import apprise_asset
        from changedetectionio.jinja2_custom import render as jinja_render
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
        notification_urls = [u for u in request.form.get('notification_urls', '').strip().splitlines() if u.strip()]

        # --- Profile-based path: no inline URLs provided, use resolved profiles for the watch ---
        if not notification_urls and watch_uuid and not is_global_settings_form and not is_group_settings_form:
            from changedetectionio.notification_profiles.resolver import resolve_notification_profiles
            if watch:
                profiles = resolve_notification_profiles(watch, datastore)
                if not profiles:
                    return make_response('Error: No notification profiles are linked to this watch (check watch, tags, and system settings)', 400)

                prev_snapshot = "Example text: example test\nExample text: change detection is cool\nExample text: some more examples\n"
                current_snapshot = "Example text: example test\nExample text: change detection is fantastic\nExample text: even more examples\nExample text: a lot more examples"
                dates = list(watch.history.keys())
                if len(dates) > 1:
                    prev_snapshot = watch.get_history_snapshot(timestamp=dates[-2])
                    current_snapshot = watch.get_history_snapshot(timestamp=dates[-1])

                errors = []
                sent = 0
                for profile, type_handler in profiles:
                    n_object = NotificationContextData({'watch_url': watch.get('url', 'https://example.com')})
                    n_object.update(set_basic_notification_vars(
                        current_snapshot=current_snapshot,
                        prev_snapshot=prev_snapshot,
                        watch=watch,
                        triggered_text='',
                        timestamp_changed=dates[-1] if dates else None,
                    ))
                    try:
                        type_handler.send(profile.get('config', {}), n_object, datastore)
                        sent += 1
                    except Exception as e:
                        logger.error(f"Test notification profile '{profile.get('name')}' failed: {e}")
                        errors.append(f"{profile.get('name', '?')}: {e}")

                if errors:
                    return make_response('; '.join(errors), 400)
                return f'OK - Sent test via {sent} profile(s)'

        # --- Legacy path: notification_urls supplied via form (global/group settings test) ---
        if not notification_urls:
            if is_global_settings_form or is_group_settings_form:
                # Try system-level profiles
                from changedetectionio.notification_profiles.resolver import resolve_notification_profiles
                if watch:
                    profiles = resolve_notification_profiles(watch, datastore)
                    if profiles:
                        prev_snapshot = "Example text: example test\nExample text: change detection is cool\n"
                        current_snapshot = "Example text: example test\nExample text: change detection is fantastic\n"
                        dates = list(watch.history.keys())
                        if len(dates) > 1:
                            prev_snapshot = watch.get_history_snapshot(timestamp=dates[-2])
                            current_snapshot = watch.get_history_snapshot(timestamp=dates[-1])

                        errors = []
                        sent = 0
                        for profile, type_handler in profiles:
                            n_object = NotificationContextData({'watch_url': watch.get('url', 'https://example.com')})
                            n_object.update(set_basic_notification_vars(
                                current_snapshot=current_snapshot,
                                prev_snapshot=prev_snapshot,
                                watch=watch,
                                triggered_text='',
                                timestamp_changed=dates[-1] if dates else None,
                            ))
                            try:
                                type_handler.send(profile.get('config', {}), n_object, datastore)
                                sent += 1
                            except Exception as e:
                                errors.append(f"{profile.get('name', '?')}: {e}")
                        if errors:
                            return make_response('; '.join(errors), 400)
                        return f'OK - Sent test via {sent} profile(s)'

            return make_response('Error: No notification profiles or URLs configured', 400)

        # Validate apprise URLs
        for n_url in notification_urls:
            generic_notification_context_data = NotificationContextData()
            generic_notification_context_data.set_random_for_validation()
            n_url_rendered = jinja_render(template_str=n_url, **generic_notification_context_data).strip()
            if n_url_rendered and not apobj.add(n_url_rendered):
                return make_response(f'Error:  {n_url} is not a valid AppRise URL.', 400)

        try:
            n_object = NotificationContextData({
                'watch_url': request.form.get('window_url', "https://changedetection.io"),
                'notification_urls': notification_urls
            })

            if 'notification_format' in request.form and request.form['notification_format'].strip():
                n_object['notification_format'] = request.form.get('notification_format', '').strip()

            if 'notification_title' in request.form and request.form['notification_title'].strip():
                n_object['notification_title'] = request.form.get('notification_title', '').strip()
            else:
                n_object['notification_title'] = "Test title"

            if 'notification_body' in request.form and request.form['notification_body'].strip():
                n_object['notification_body'] = request.form.get('notification_body', '').strip()
            else:
                n_object['notification_body'] = "Test body"

            n_object['as_async'] = False

            dates = list(watch.history.keys()) if watch else []
            prev_snapshot = "Example text: example test\nExample text: change detection is cool\nExample text: some more examples\n"
            current_snapshot = "Example text: example test\nExample text: change detection is fantastic\nExample text: even more examples\nExample text: a lot more examples"

            if len(dates) > 1:
                prev_snapshot = watch.get_history_snapshot(timestamp=dates[-2])
                current_snapshot = watch.get_history_snapshot(timestamp=dates[-1])

            n_object.update(set_basic_notification_vars(current_snapshot=current_snapshot,
                                                        prev_snapshot=prev_snapshot,
                                                        watch=watch,
                                                        triggered_text='',
                                                        timestamp_changed=dates[-1] if dates else None))

            sent_obj = process_notification(n_object, datastore)

        except Exception as e:
            logger.error(e)
            e_str = str(e)
            e_str = e_str.replace(
                "DEBUG - <class 'apprise.decorators.base.CustomNotifyPlugin.instantiate_plugin.<locals>.CustomNotifyPluginWrapper'>",
                '')
            return make_response(e_str, 400)

        return 'OK - Sent test notifications'

    return notification_blueprint
