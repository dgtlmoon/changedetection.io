import os
from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones
import secrets
import time
import flask_login
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_babel import gettext

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    settings_blueprint = Blueprint('settings', __name__, template_folder="templates")

    @settings_blueprint.route("", methods=['GET', "POST"])
    @login_optionally_required
    def settings_page():
        from changedetectionio import forms
        from changedetectionio.pluggy_interface import (
            get_plugin_settings_tabs,
            load_plugin_settings,
            save_plugin_settings
        )


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
                    flash(gettext("Password protection removed."), 'notice')
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
                datastore.commit()

                # Adjust worker count if it changed
                if new_worker_count != old_worker_count:
                    from changedetectionio import worker_pool
                    from changedetectionio.flask_app import update_q, notification_q, app, datastore as ds

                    # Check CPU core availability and warn if worker count is high
                    cpu_count = os.cpu_count()
                    if cpu_count and new_worker_count >= (cpu_count * 0.9):
                        flash(gettext("Warning: Worker count ({}) is close to or exceeds available CPU cores ({})").format(
                            new_worker_count, cpu_count), 'warning')

                    result = worker_pool.adjust_async_worker_count(
                        new_count=new_worker_count,
                        update_q=update_q,
                        notification_q=notification_q,
                        app=app,
                        datastore=ds
                    )

                    if result['status'] == 'success':
                        flash(gettext("Worker count adjusted: {}").format(result['message']), 'notice')
                    elif result['status'] == 'not_supported':
                        flash(gettext("Dynamic worker adjustment not supported for sync workers"), 'warning')
                    elif result['status'] == 'error':
                        flash(gettext("Error adjusting workers: {}").format(result['message']), 'error')

                if not os.getenv("SALTED_PASS", False) and len(form.application.form.password.encrypted_password):
                    datastore.data['settings']['application']['password'] = form.application.form.password.encrypted_password
                    datastore.commit()
                    flash(gettext("Password protection enabled."), 'notice')
                    flask_login.logout_user()
                    return redirect(url_for('watchlist.index'))

                # Also save plugin settings from the same form submission
                plugin_tabs_list = get_plugin_settings_tabs()
                for tab in plugin_tabs_list:
                    plugin_id = tab['plugin_id']
                    form_class = tab['form_class']

                    # Instantiate plugin form with POST data
                    plugin_form = form_class(formdata=request.form)

                    # Save plugin settings (validation is optional for plugins)
                    if plugin_form.data:
                        save_plugin_settings(datastore.datastore_path, plugin_id, plugin_form.data)

                flash(gettext("Settings updated."))

            else:
                flash(gettext("An error occurred, please see below."), "error")

        # Convert to ISO 8601 format, all date/time relative events stored as UTC time
        utc_time = datetime.now(ZoneInfo("UTC")).isoformat()

        # Get active plugins
        from changedetectionio.pluggy_interface import get_active_plugins
        import sys
        active_plugins = get_active_plugins()
        python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # Calculate uptime in seconds
        uptime_seconds = time.time() - datastore.start_time

        # Get plugin settings tabs and instantiate forms
        plugin_tabs = get_plugin_settings_tabs()
        plugin_forms = {}

        for tab in plugin_tabs:
            plugin_id = tab['plugin_id']
            form_class = tab['form_class']

            # Load existing settings
            settings = load_plugin_settings(datastore.datastore_path, plugin_id)

            # Instantiate the form with existing settings
            plugin_forms[plugin_id] = form_class(data=settings)

        output = render_template("settings.html",
                                active_plugins=active_plugins,
                                api_key=datastore.data['settings']['application'].get('api_access_token'),
                                python_version=python_version,
                                uptime_seconds=uptime_seconds,
                                available_timezones=sorted(available_timezones()),
                                emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
                                extra_notification_token_placeholder_info=datastore.get_unique_notification_token_placeholders_available(),
                                form=form,
                                hide_remove_pass=os.getenv("SALTED_PASS", False),
                                min_system_recheck_seconds=int(os.getenv('MINIMUM_SECONDS_RECHECK_TIME', 3)),
                                settings_application=datastore.data['settings']['application'],
                                timezone_default_config=datastore.data['settings']['application'].get('scheduler_timezone_default'),
                                utc_time=utc_time,
                                plugin_tabs=plugin_tabs,
                                plugin_forms=plugin_forms,
                                )

        return output

    @settings_blueprint.route("/reset-api-key", methods=['GET'])
    @login_optionally_required
    def settings_reset_api_key():
        secret = secrets.token_hex(16)
        datastore.data['settings']['application']['api_access_token'] = secret
        datastore.commit()
        flash(gettext("API Key was regenerated."))
        return redirect(url_for('settings.settings_page')+'#api')
        
    @settings_blueprint.route("/notification-logs", methods=['GET'])
    @login_optionally_required
    def notification_logs():
        from changedetectionio.flask_app import notification_debug_log
        output = render_template("notification-log.html",
                               logs=notification_debug_log if len(notification_debug_log) else ["Notification logs are empty - no notifications sent yet."])
        return output

    @settings_blueprint.route("/toggle-all-paused", methods=['GET'])
    @login_optionally_required
    def toggle_all_paused():
        current_state = datastore.data['settings']['application'].get('all_paused', False)
        datastore.data['settings']['application']['all_paused'] = not current_state
        datastore.commit()

        if datastore.data['settings']['application']['all_paused']:
            flash(gettext("Automatic scheduling paused - checks will not be queued."), 'notice')
        else:
            flash(gettext("Automatic scheduling resumed - checks will be queued normally."), 'notice')

        return redirect(url_for('watchlist.index'))

    @settings_blueprint.route("/toggle-all-muted", methods=['GET'])
    @login_optionally_required
    def toggle_all_muted():
        current_state = datastore.data['settings']['application'].get('all_muted', False)
        datastore.data['settings']['application']['all_muted'] = not current_state
        datastore.commit()

        if datastore.data['settings']['application']['all_muted']:
            flash(gettext("All notifications muted."), 'notice')
        else:
            flash(gettext("All notifications unmuted."), 'notice')

        return redirect(url_for('watchlist.index'))

    return settings_blueprint