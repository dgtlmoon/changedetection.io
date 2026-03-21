import uuid as uuid_mod
from flask import Blueprint, request, render_template, flash, redirect, url_for, make_response
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    bp = Blueprint('notification_profiles', __name__, template_folder="templates")

    def _profiles():
        return datastore.data['settings']['application'].setdefault('notification_profile_data', {})

    @bp.route("/", methods=['GET'])
    @login_optionally_required
    def index():
        from changedetectionio.notification_profiles.registry import registry
        from changedetectionio.notification_profiles.log import read_profile_log

        profiles = _profiles()

        # Count how many watches/tags reference each profile
        usage = {}
        for watch in datastore.data['watching'].values():
            for u in watch.get('notification_profiles', []):
                usage[u] = usage.get(u, 0) + 1
        for tag in datastore.data['settings']['application'].get('tags', {}).values():
            for u in tag.get('notification_profiles', []):
                usage[u] = usage.get(u, 0) + 1

        # Most-recent log entry per profile (for the Last result column)
        last_log = {}
        for uid in profiles:
            entries = read_profile_log(datastore.datastore_path, uid)
            if entries:
                last_log[uid] = entries[0]   # newest first

        return render_template(
            "notification_profiles/list.html",
            profiles=profiles,
            registry=registry,
            usage=usage,
            last_log=last_log,
        )

    @bp.route("/new", methods=['GET', 'POST'])
    @bp.route("/<uuid_str:profile_uuid>", methods=['GET', 'POST'])
    @login_optionally_required
    def edit(profile_uuid=None):
        from changedetectionio.notification_profiles.registry import registry
        from .forms import NotificationProfileForm

        profiles = _profiles()
        existing = profiles.get(profile_uuid, {}) if profile_uuid else {}

        form = NotificationProfileForm(
            request.form if request.method == 'POST' else None,
            data=existing or None,
        )

        if request.method == 'POST' and form.validate():
            profile_type = form.profile_type.data or 'apprise'
            type_handler = registry.get(profile_type)

            # Build type-specific config from submitted form data
            config = _extract_config(request.form, profile_type)

            try:
                type_handler.validate(config)
            except ValueError as e:
                flash(str(e), 'error')
                return render_template("notification_profiles/edit.html",
                                       form=form, profile_uuid=profile_uuid,
                                       registry=registry, existing=existing)

            uid = profile_uuid or str(uuid_mod.uuid4())
            profiles[uid] = {
                'uuid':   uid,
                'name':   form.name.data.strip(),
                'type':   profile_type,
                'config': config,
            }
            datastore.commit()
            flash(gettext("Notification profile saved."), 'notice')
            return redirect(url_for('notification_profiles.index'))

        return render_template(
            "notification_profiles/edit.html",
            form=form,
            profile_uuid=profile_uuid,
            registry=registry,
            existing=existing,
        )

    @bp.route("/<uuid_str:profile_uuid>/delete", methods=['POST'])
    @login_optionally_required
    def delete(profile_uuid):
        profiles = _profiles()
        if profile_uuid not in profiles:
            flash(gettext("Profile not found."), 'error')
            return redirect(url_for('notification_profiles.index'))

        # Warn if in use — but allow deletion
        usage_count = sum(
            1 for w in datastore.data['watching'].values()
            if profile_uuid in w.get('notification_profiles', [])
        )

        del profiles[profile_uuid]
        datastore.commit()

        if usage_count:
            flash(gettext("Profile deleted (was linked to %(n)d watch(es)).", n=usage_count), 'notice')
        else:
            flash(gettext("Profile deleted."), 'notice')

        return redirect(url_for('notification_profiles.index'))

    @bp.route("/<uuid_str:profile_uuid>/test", methods=['POST'])
    @login_optionally_required
    def test(profile_uuid):
        """Fire a test notification for a saved profile."""
        from changedetectionio.notification_service import NotificationContextData, set_basic_notification_vars
        import random

        profiles = _profiles()
        profile = profiles.get(profile_uuid)
        if not profile:
            return make_response("Profile not found", 404)

        from changedetectionio.notification_profiles.registry import registry
        type_handler = registry.get(profile.get('type', 'apprise'))

        # Pick a random watch for context variables
        watch_uuid = request.form.get('watch_uuid')
        if not watch_uuid and datastore.data.get('watching'):
            watch_uuid = random.choice(list(datastore.data['watching'].keys()))

        if not watch_uuid:
            return make_response("Error: No watches configured for test notification", 400)

        watch = datastore.data['watching'].get(watch_uuid)
        prev_snapshot    = "Example text: example test\nExample text: change detection is cool\n"
        current_snapshot = "Example text: example test\nExample text: change detection is fantastic\n"

        dates = list(watch.history.keys()) if watch else []
        if len(dates) > 1:
            prev_snapshot    = watch.get_history_snapshot(timestamp=dates[-2])
            current_snapshot = watch.get_history_snapshot(timestamp=dates[-1])

        n_object = NotificationContextData({'watch_url': watch.get('url', 'https://example.com') if watch else 'https://example.com'})
        n_object.update(set_basic_notification_vars(
            current_snapshot=current_snapshot,
            prev_snapshot=prev_snapshot,
            watch=watch,
            triggered_text='',
            timestamp_changed=dates[-1] if dates else None,
        ))

        from changedetectionio.notification_profiles.log import write_profile_log
        try:
            type_handler.send(profile.get('config', {}), n_object, datastore)
            write_profile_log(datastore.datastore_path, profile_uuid,
                              watch_url=watch.get('url', '') if watch else '',
                              watch_uuid=watch_uuid or '',
                              status='test', message='Manual test')
        except Exception as e:
            logger.error(f"Test notification failed for profile {profile_uuid}: {e}")
            write_profile_log(datastore.datastore_path, profile_uuid,
                              watch_url=watch.get('url', '') if watch else '',
                              watch_uuid=watch_uuid or '',
                              status='error', message=str(e))
            return make_response(str(e), 400)

        return 'OK - Test notification sent'

    @bp.route("/<uuid_str:profile_uuid>/log", methods=['GET'])
    @login_optionally_required
    def profile_log(profile_uuid):
        """Show per-profile send history."""
        from changedetectionio.notification_profiles.log import read_profile_log
        profiles = _profiles()
        profile = profiles.get(profile_uuid)
        if not profile:
            flash(gettext("Profile not found."), 'error')
            return redirect(url_for('notification_profiles.index'))

        entries = read_profile_log(datastore.datastore_path, profile_uuid)
        return render_template('notification_profiles/log.html',
                               profile=profile,
                               entries=entries,
                               profile_uuid=profile_uuid)

    return bp


def _extract_config(form_data, profile_type: str) -> dict:
    """Extract type-specific config fields from form POST data."""
    if profile_type == 'apprise':
        raw = form_data.get('notification_urls', '')
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        return {
            'notification_urls':  urls,
            'notification_title': form_data.get('notification_title', '').strip() or None,
            'notification_body':  form_data.get('notification_body', '').strip() or None,
            'notification_format': form_data.get('notification_format', '').strip() or None,
        }
    # Other types: plugins populate their own config keys
    return dict(form_data)
