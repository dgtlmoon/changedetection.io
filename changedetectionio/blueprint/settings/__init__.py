import os
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones
import secrets
import flask_login
from flask import Blueprint, render_template, request, redirect, url_for, flash

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    settings_blueprint = Blueprint('settings', __name__, template_folder="templates")

    @settings_blueprint.route("", methods=['GET', "POST"])
    @login_optionally_required
    def settings_page():
        from changedetectionio import forms

        default = deepcopy(datastore.data['settings'])
        if datastore.proxy_list is not None:
            available_proxies = list(datastore.proxy_list.keys())
            # When enabled
            system_proxy = datastore.data['settings']['requests']['proxy']
            # In the case it doesnt exist anymore
            if not system_proxy in available_proxies:
                system_proxy = None

            default['requests']['proxy'] = system_proxy if system_proxy is not None else available_proxies[0]
            # Used by the form handler to keep or remove the proxy settings
            default['proxy_list'] = available_proxies[0]

        # Don't use form.data on POST so that it doesnt overrid the checkbox status from the POST status
        form = forms.globalSettingsForm(formdata=request.form if request.method == 'POST' else None,
                                        data=default,
                                        extra_notification_tokens=datastore.get_unique_notification_tokens_available()
                                        )

        # Remove the last option 'System default'
        form.application.form.notification_format.choices.pop()

        if datastore.proxy_list is None:
            # @todo - Couldn't get setattr() etc dynamic addition working, so remove it instead
            del form.requests.form.proxy
        else:
            form.requests.form.proxy.choices = []
            for p in datastore.proxy_list:
                form.requests.form.proxy.choices.append(tuple((p, datastore.proxy_list[p]['label'])))

        if request.method == 'POST':
            # Password unset is a GET, but we can lock the session to a salted env password to always need the password
            if form.application.form.data.get('removepassword_button', False):
                # SALTED_PASS means the password is "locked" to what we set in the Env var
                if not os.getenv("SALTED_PASS", False):
                    datastore.remove_password()
                    flash("Password protection removed.", 'notice')
                    flask_login.logout_user()
                    return redirect(url_for('settings.settings_page'))

            if form.validate():
                # Don't set password to False when a password is set - should be only removed with the `removepassword` button
                app_update = dict(deepcopy(form.data['application']))

                # Never update password with '' or False (Added by wtforms when not in submission)
                if 'password' in app_update and not app_update['password']:
                    del (app_update['password'])

                datastore.data['settings']['application'].update(app_update)
                
                # Handle dynamic worker count adjustment
                old_worker_count = datastore.data['settings']['requests'].get('workers', 1)
                new_worker_count = form.data['requests'].get('workers', 1)
                
                datastore.data['settings']['requests'].update(form.data['requests'])
                
                # Adjust worker count if it changed
                if new_worker_count != old_worker_count:
                    from changedetectionio import worker_handler
                    from changedetectionio.flask_app import update_q, notification_q, app, datastore as ds
                    
                    result = worker_handler.adjust_async_worker_count(
                        new_count=new_worker_count,
                        update_q=update_q,
                        notification_q=notification_q,
                        app=app,
                        datastore=ds
                    )
                    
                    if result['status'] == 'success':
                        flash(f"Worker count adjusted: {result['message']}", 'notice')
                    elif result['status'] == 'not_supported':
                        flash("Dynamic worker adjustment not supported for sync workers", 'warning')
                    elif result['status'] == 'error':
                        flash(f"Error adjusting workers: {result['message']}", 'error')

                if not os.getenv("SALTED_PASS", False) and len(form.application.form.password.encrypted_password):
                    datastore.data['settings']['application']['password'] = form.application.form.password.encrypted_password
                    datastore.needs_write_urgent = True
                    flash("Password protection enabled.", 'notice')
                    flask_login.logout_user()
                    return redirect(url_for('watchlist.index'))

                datastore.needs_write_urgent = True
                flash("Settings updated.")

            else:
                flash("An error occurred, please see below.", "error")

        # Convert to ISO 8601 format, all date/time relative events stored as UTC time
        utc_time = datetime.now(ZoneInfo("UTC")).isoformat()

        output = render_template("settings.html",
                                api_key=datastore.data['settings']['application'].get('api_access_token'),
                                available_timezones=sorted(available_timezones()),
                                emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                                extra_notification_token_placeholder_info=datastore.get_unique_notification_token_placeholders_available(),
                                form=form,
                                hide_remove_pass=os.getenv("SALTED_PASS", False),
                                min_system_recheck_seconds=int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3)),
                                settings_application=datastore.data['settings']['application'],
                                timezone_default_config=datastore.data['settings']['application'].get('timezone'),
                                utc_time=utc_time,
                                )

        return output

    @settings_blueprint.route("/reset-api-key", methods=['GET'])
    @login_optionally_required
    def settings_reset_api_key():
        secret = secrets.token_hex(16)
        datastore.data['settings']['application']['api_access_token'] = secret
        datastore.needs_write_urgent = True
        flash("API Key was regenerated.")
        return redirect(url_for('settings.settings_page')+'#api')
        
    @settings_blueprint.route("/notification-logs", methods=['GET'])
    @login_optionally_required
    def notification_logs():
        from changedetectionio.flask_app import notification_debug_log
        output = render_template("notification-log.html",
                               logs=notification_debug_log if len(notification_debug_log) else ["Notification logs are empty - no notifications sent yet."])
        return output

    return settings_blueprint