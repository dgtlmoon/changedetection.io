import flask_login
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_babel import gettext

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    settings_browser_profile_blueprint = Blueprint(
        'settings_browsers',
        __name__,
        template_folder="templates"
    )

    def _render_index(browser_profile_form=None, editing_machine_name=None):
        from changedetectionio import forms
        from changedetectionio import content_fetchers as cf
        from changedetectionio.model.browser_profile import BrowserProfile, RESERVED_MACHINE_NAMES

        # Only browser-capable fetchers are valid profile types
        fetcher_choices = cf.available_browser_fetchers()
        if browser_profile_form is None:
            browser_profile_form = forms.BrowserProfileForm()
        browser_profile_form.fetch_backend.choices = fetcher_choices

        fetcher_supports_screenshots = {name: True for name, _ in fetcher_choices}
        fetcher_requires_connection_url = {name: True for name, cls in cf.FETCHERS.items()
                                           if getattr(cls, 'requires_connection_url', False)}

        # Table shows default built-in profiles first, then user-created profiles
        store_profiles = datastore.data['settings']['application'].get('browser_profiles', {})
        user_profiles = dict(cf.DEFAULT_BROWSER_PROFILES)
        for machine_name, raw in store_profiles.items():
            try:
                user_profiles[machine_name] = BrowserProfile(**raw) if isinstance(raw, dict) else raw
            except Exception:
                pass

        current_default = datastore.data['settings']['application'].get('browser_profile') or 'direct_http_requests'

        return render_template(
            "browser_profiles.html",
            browser_profiles=user_profiles,
            browser_profile_form=browser_profile_form,
            reserved_browser_profile_names=RESERVED_MACHINE_NAMES,
            fetcher_choices=fetcher_choices,
            fetcher_supports_screenshots=fetcher_supports_screenshots,
            fetcher_requires_connection_url=fetcher_requires_connection_url,
            current_default_profile=current_default,
            editing_machine_name=editing_machine_name,
        )

    @settings_browser_profile_blueprint.route("", methods=['GET'])
    @login_optionally_required
    def index():
        return _render_index()

    @settings_browser_profile_blueprint.route("/<string:machine_name>/edit", methods=['GET'])
    @login_optionally_required
    def edit(machine_name):
        from changedetectionio import forms
        from changedetectionio.model.browser_profile import BrowserProfile, RESERVED_MACHINE_NAMES

        if machine_name in RESERVED_MACHINE_NAMES:
            flash(gettext("Built-in browser profiles cannot be edited."), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        store_profiles = datastore.data['settings']['application'].get('browser_profiles', {})
        raw = store_profiles.get(machine_name)
        if raw is None:
            flash(gettext("Browser profile not found."), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        profile = BrowserProfile(**raw) if isinstance(raw, dict) else raw
        form = forms.BrowserProfileForm(data=profile.model_dump())
        return _render_index(browser_profile_form=form, editing_machine_name=machine_name)

    @settings_browser_profile_blueprint.route("/save", methods=['POST'])
    @login_optionally_required
    def save():
        from changedetectionio import forms
        from changedetectionio import content_fetchers as cf
        from changedetectionio.model.browser_profile import BrowserProfile, RESERVED_MACHINE_NAMES

        fetcher_choices = [(name, desc) for name, desc in cf.available_fetchers()]
        browser_profile_form = forms.BrowserProfileForm(formdata=request.form)
        browser_profile_form.fetch_backend.choices = fetcher_choices

        if not browser_profile_form.validate():
            flash(gettext("Browser profile error: {}").format(
                '; '.join(str(e) for errs in browser_profile_form.errors.values() for e in errs)
            ), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        name = browser_profile_form.name.data.strip()
        machine_name = BrowserProfile.machine_name_from_str(name)

        if machine_name in RESERVED_MACHINE_NAMES:
            flash(gettext("Cannot use reserved profile name '{}'. Please choose a different name.").format(name), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        original_machine_name = request.form.get('original_machine_name', '').strip()
        store_profiles = datastore.data['settings']['application'].setdefault('browser_profiles', {})

        if machine_name != original_machine_name and machine_name in store_profiles:
            flash(gettext("A browser profile named '{}' already exists.").format(name), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        profile_data = {
            'name': name,
            'fetch_backend': browser_profile_form.fetch_backend.data,
            'browser_connection_url': browser_profile_form.browser_connection_url.data or None,
            'viewport_width': browser_profile_form.viewport_width.data or 1280,
            'viewport_height': browser_profile_form.viewport_height.data or 1000,
            'block_images': bool(browser_profile_form.block_images.data),
            'block_fonts': bool(browser_profile_form.block_fonts.data),
            'ignore_https_errors': bool(browser_profile_form.ignore_https_errors.data),
            'user_agent': browser_profile_form.user_agent.data or None,
            'locale': browser_profile_form.locale.data or None,
            'custom_headers': browser_profile_form.custom_headers.data or '',
            'is_builtin': False,
        }

        try:
            BrowserProfile(**profile_data)
        except Exception as e:
            flash(gettext("Browser profile validation error: {}").format(str(e)), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        # Handle rename: remove old key, cascade-update watches and tags
        if original_machine_name and original_machine_name != machine_name and original_machine_name in store_profiles:
            del store_profiles[original_machine_name]
            for watch in datastore.data['watching'].values():
                if watch.get('browser_profile') == original_machine_name:
                    watch['browser_profile'] = machine_name
            for tag in datastore.data.get('settings', {}).get('application', {}).get('tags', {}).values():
                if tag.get('browser_profile') == original_machine_name:
                    tag['browser_profile'] = machine_name

        store_profiles[machine_name] = profile_data
        datastore.commit()
        flash(gettext("Browser profile '{}' saved.").format(name), 'notice')
        return redirect(url_for('settings.settings_browsers.index'))

    @settings_browser_profile_blueprint.route("/<string:machine_name>/delete", methods=['GET'])
    @login_optionally_required
    def delete(machine_name):
        from changedetectionio.model.browser_profile import RESERVED_MACHINE_NAMES

        if machine_name in RESERVED_MACHINE_NAMES:
            flash(gettext("Built-in browser profiles cannot be deleted."), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        store_profiles = datastore.data['settings']['application'].get('browser_profiles', {})
        if machine_name not in store_profiles:
            flash(gettext("Browser profile not found."), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        raw = store_profiles[machine_name]
        profile_name = raw.get('name', machine_name) if isinstance(raw, dict) else machine_name

        for watch in datastore.data['watching'].values():
            if watch.get('browser_profile') == machine_name:
                watch['browser_profile'] = None

        for tag in datastore.data.get('settings', {}).get('application', {}).get('tags', {}).values():
            if tag.get('browser_profile') == machine_name:
                tag['browser_profile'] = None

        if datastore.data['settings']['application'].get('browser_profile') == machine_name:
            datastore.data['settings']['application']['browser_profile'] = None

        del store_profiles[machine_name]
        datastore.commit()
        flash(gettext("Browser profile '{}' deleted.").format(profile_name), 'notice')
        return redirect(url_for('settings.settings_browsers.index'))

    @settings_browser_profile_blueprint.route("/set-default", methods=['POST'])
    @login_optionally_required
    def set_default():
        from changedetectionio import content_fetchers as cf

        machine_name = request.form.get('machine_name', '').strip()
        if not machine_name:
            flash(gettext("No profile specified."), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        from changedetectionio.model.browser_profile import get_profile
        store_profiles = datastore.data['settings']['application'].get('browser_profiles', {})
        if get_profile(machine_name, store_profiles) is None:
            flash(gettext("Unknown browser profile '{}'.").format(machine_name), 'error')
            return redirect(url_for('settings.settings_browsers.index'))

        datastore.data['settings']['application']['browser_profile'] = machine_name
        datastore.commit()
        flash(gettext("Default browser profile set to '{}'.").format(machine_name), 'notice')
        return redirect(url_for('settings.settings_browsers.index'))

    return settings_browser_profile_blueprint
