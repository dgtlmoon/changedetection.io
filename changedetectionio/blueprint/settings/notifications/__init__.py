"""
Notification settings — child blueprint of /settings.

Registered by the parent settings blueprint at url_prefix='/notifications', so the
URLs land at /settings/notifications/<backend>. Today the only backend is apprise;
future backends (simple_email, raw webhooks, etc.) slot in as sibling routes here
without re-shaping the URL space again.

The eventual data-model refactor is to give each notification config its own
uuid (`notification_uuid`) referenced from global/watch/group settings, instead
of inlining apprise URL strings on every record — that's not done here; this
file just gives that future work a stable home.
"""
import os

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_babel import gettext

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_notifications_blueprint(datastore: ChangeDetectionStore):
    notifications_blueprint = Blueprint(
        'notifications', __name__,
        template_folder="templates",
    )

    @notifications_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def index():
        # /settings/notifications/ → apprise (only backend for now).
        # When a second backend lands this becomes a chooser.
        return redirect(url_for('settings.notifications.apprise'))

    @notifications_blueprint.route("/apprise", methods=['GET', 'POST'])
    @login_optionally_required
    def apprise():
        from changedetectionio import forms

        app_settings = datastore.data['settings']['application']
        # Seed the form with the currently stored values so GET (and a failed
        # POST that re-renders) shows what's persisted, not WTForms defaults.
        default = {
            'notification_urls': app_settings.get('notification_urls') or [],
            'notification_title': app_settings.get('notification_title') or '',
            'notification_body': app_settings.get('notification_body') or '',
            'notification_format': app_settings.get('notification_format') or '',
            'base_url': app_settings.get('base_url') or '',
        }

        form = forms.globalSettingsAppriseNotificationForm(
            formdata=request.form if request.method == 'POST' else None,
            data=default,
            extra_notification_tokens=datastore.get_unique_notification_tokens_available(),
        )

        if request.method == 'POST' and form.validate():
            for field in ('notification_urls', 'notification_title', 'notification_body',
                          'notification_format', 'base_url'):
                app_settings[field] = form.data.get(field)
            datastore.commit()
            flash(gettext("Settings updated."))
            return redirect(url_for('settings.notifications.apprise'))
        elif request.method == 'POST':
            flash(gettext("An error occurred, please see below."), "error")

        return render_template(
            "apprise.html",
            form=form,
            emailprefix=os.getenv('NOTIFICATION_MAIL_BUTTON_PREFIX', False),
            extra_notification_token_placeholder_info=datastore.get_unique_notification_token_placeholders_available(),
            settings_application=app_settings,
        )

    return notifications_blueprint
