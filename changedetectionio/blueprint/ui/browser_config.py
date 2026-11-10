"""
Browsers blueprint - manage named browser configs ("profiles").

Lists the available base content fetchers (engines) with their capabilities, and lets the
user add / edit / remove / set-default browser configs, persisted in browsers.json via
datastore.browser_config_store.

Registered as a sub-blueprint of `ui`, so endpoints are `ui.browser_config.*`.
"""
import os

from flask import Blueprint, jsonify, request, render_template, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger
from pydantic import ValidationError

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.strtobool import strtobool
from changedetectionio.flask_app import login_optionally_required


def _browser_config_locked():
    """LOCKED_BROWSER_CONFIG: viewing + choosing the default browser stay available, but
    adding / editing / removing configs is disabled. Mirrors the browser_config_locked()
    template global (same env + strtobool contract) - kept here to avoid importing view
    helpers back into the blueprint."""
    return bool(strtobool(os.getenv('LOCKED_BROWSER_CONFIG', 'False')))


def _base_fetchers(datastore):
    """Every available base engine shown as a row in "Available browsers".

    Includes the plain HTTP client ('html_requests') and any other non-browser fetchers, not just
    browser-capable engines: /browsers is the only place the global Default browser is set, and the
    plaintext client is the most common default, so it MUST be selectable here. Per-row flags tell
    the template which actions apply:
      - is_browser (supports screenshots / visual-selector) -> can "Add variation" + "Edit"
      - ready_to_use (usable directly, not base-only like html_playwright_builtin) -> can be default
    A ready-to-use engine may have a stored built-in override config (keyed by the engine name).
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    out = []
    for name, description in content_fetchers.available_fetchers():
        cls = getattr(content_fetchers, name, None)
        caps = FetcherCapabilities.from_fetcher(cls)
        stored = datastore.browser_config_store.get(name) or {}
        out.append({
            'name': name,
            'description': description,
            'capabilities': caps.model_dump(),
            # The capabilities worth showing a user, with their translated label + icon
            'capability_chips': caps.chips(),
            'browser_config': stored.get('browser_config') or {},
            'ready_to_use': getattr(cls, 'ready_to_use', True),
            'is_browser': caps.is_browser,
            'configurable': caps.can_host_variation,
        })
    # Browsers first (richer rows), plain fetchers (e.g. html_requests) after, stable by name.
    out.sort(key=lambda f: (not f['is_browser'], f['name']))
    return out


def _autocomplete_choices():
    """(locales, timezones) for the datalist autocompletes - same sources the FetcherConfig
    validators use (babel CLDR + stdlib zoneinfo)."""
    from zoneinfo import available_timezones
    timezones = sorted(available_timezones())
    try:
        from babel.localedata import locale_identifiers
        locales = sorted({lid.replace('_', '-') for lid in locale_identifiers()})
    except Exception:
        locales = ['en-US', 'en-GB', 'de-DE', 'fr-FR', 'es-ES', 'it-IT', 'ja-JP', 'zh-CN', 'pt-BR', 'nl-NL']
    return locales, timezones


def _caps_for(base_name):
    """Capability dict for an engine, so the form renders only the fields it can honour
    (e.g. html_requests has no screenshots -> no viewport/locale/timezone)."""
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    return FetcherCapabilities.from_fetcher(getattr(content_fetchers, base_name, None)).model_dump()


def _applicable_fields_for(capabilities):
    """The FetcherConfig fields an engine with these capabilities may carry - the one set that
    both the form template and the save path use, so they cannot drift apart."""
    from changedetectionio.model.browser_config import FetcherConfig
    return FetcherConfig.applicable_fields(capabilities)


def _entry_to_formdata(entry, sections=()):
    """Flatten a browsers.json entry into flat form field values (base is contextual, not a field).
    Each plugin section's saved settings go to its sub-form (plugin_<id>)."""
    data = {'label': entry.get('label')}
    data.update(entry.get('browser_config') or {})
    saved = data.pop('plugin_settings', None) or {}
    for section in sections:
        data[section.field_name] = saved.get(section.plugin_id) or {}
    return data


def _plugin_sections_and_form(base_fetcher, capabilities):
    """Plugin sections for this engine, and BrowserOptionsForm with their sub-forms attached."""
    from .form_browseroptions import BrowserOptionsForm
    from changedetectionio.browser_lifecycle import form_class_with_sections, get_browser_config_sections
    sections = get_browser_config_sections(base_fetcher, capabilities)
    return sections, form_class_with_sections(BrowserOptionsForm, sections)


def _wants_modal():
    """?modal=1: the /browsers page loads the add/edit form into its dialog (browser-config-modal.js)
    instead of opening it as a page. Without it the same routes are ordinary pages, which is also
    what a browser without <dialog> or JavaScript gets."""
    return request.args.get('modal') == '1'


def _saved(message):
    """A browser was added/updated: back to the overview with `message`. The dialog gets the
    address as JSON and goes there itself, so the flash shows on the reloaded overview."""
    flash(message)
    overview = url_for('ui.browser_config.browsers_overview')
    if _wants_modal():
        return jsonify({'ok': True, 'redirect': overview})
    return redirect(overview)


def _render_form(form, mode, base_fetcher, base_label, sections, capabilities, form_endpoint, **context):
    """The add/edit form, as a page or (?modal=1) as the fragment the dialog loads.

    Both lay out the same panes (_browser_config_fields.html); which optional panes exist is
    decided here so the page's tabs and the dialog's sections can't disagree.
    """
    applicable = _applicable_fields_for(capabilities)
    locale_choices, timezone_choices = _autocomplete_choices()
    section_tabs = {section.tab for section in sections}
    modal = _wants_modal()
    return render_template(
        "browser-config-modal.html" if modal else "browser-config-form.html",
        form=form, mode=mode, base_fetcher=base_fetcher, base_label=base_label,
        plugin_sections=sections, applicable=applicable,
        show_language_tab=bool(applicable & {'locale', 'timezone_id'}) or 'language' in section_tabs,
        show_request_tab=bool(applicable & {'timeout', 'user_agent', 'block_resource_types', 'block_url_patterns'})
                         or 'request' in section_tabs,
        locale_choices=locale_choices, timezone_choices=timezone_choices,
        # Keep ?modal=1 on the POST, so a validation error comes back as a fragment too
        form_action=url_for(form_endpoint[0], modal='1' if modal else None, **form_endpoint[1]),
        **context)


def construct_blueprint(datastore: ChangeDetectionStore):
    browser_config_blueprint = Blueprint('browser_config', __name__, template_folder="templates")

    @browser_config_blueprint.route("/browsers", methods=['GET'])
    @login_optionally_required
    def browsers_overview():
        base_fetchers = _base_fetchers(datastore)
        # Nest each user-created variation under the engine it extends, so a variation reads as a
        # child of its base browser (↳) instead of living in a separate "Your browsers" table.
        # Variations are uuid-keyed with a `base_fetcher`; built-in engine override configs are
        # keyed by the engine name itself (cid == base_fetcher) - those are the base row's own
        # "Edit", not a variation, so they're skipped here.
        variations_by_base = {}
        from changedetectionio.model.browser_config import browser_config_usage
        usage = browser_config_usage(datastore)
        no_usage = {'watches': 0, 'groups': 0}
        for cid, entry in datastore.browser_config_store.all().items():
            base = entry.get('base_fetcher')
            if cid == base:
                continue
            variations_by_base.setdefault(base, []).append({'id': cid, 'usage': usage.get(cid, no_usage), **entry})
        for f in base_fetchers:
            f['variations'] = variations_by_base.get(f['name'], [])
            f['usage'] = usage.get(f['name'], no_usage)
        return render_template(
            "browsers-overview.html",
            base_fetchers=base_fetchers,
            # The default browser is the global system fetch_backend (single source of truth).
            default_browser_id=datastore.data['settings']['application'].get('fetch_backend'),
        )

    def _label_is_taken(label, exclude_id=None):
        """True if another browser config already uses this label (case-insensitive).
        Also guards against colliding with a built-in engine's name."""
        from changedetectionio.model.browser_config import list_builtin_browsers
        norm = (label or '').strip().lower()
        for b in list_builtin_browsers():
            if b['label'].strip().lower() == norm:
                return True
        for cid, entry in datastore.browser_config_store.all().items():
            if cid != exclude_id and (entry.get('label') or '').strip().lower() == norm:
                return True
        return False

    def _validate_and_build_config(form, capabilities, sections=(), saved_plugin_settings=None):
        """Return a validated FetcherConfig, or None (with errors attached to form).

        Each plugin section's sub-form becomes plugin_settings[<plugin_id>]. Settings of plugins
        that aren't offering a section right now (uninstalled, or unavailable here) are kept as
        they were, so saving the page never wipes them.

        `capabilities` is the base engine's capability set and acts as the allowlist: only fields
        that engine can honour are taken from the submitted form (FetcherConfig.from_submitted),
        so nothing this browser ignores can be written into browsers.json.
        """
        from changedetectionio.model.browser_config import FetcherConfig
        try:
            data = form.to_fetcher_config_dict()
            from changedetectionio.browser_lifecycle import section_settings_error
            plugin_settings = dict(saved_plugin_settings or {})
            for section in sections:
                section_data = getattr(form, section.field_name).data
                problem = section_settings_error(section_data)
                if problem:
                    logger.error(f"Refusing settings from plugin '{section.plugin_id}': {problem}")
                    flash(f"{section.label}: {problem}", 'error')
                    return None
                plugin_settings[section.plugin_id] = section_data
            if plugin_settings:
                data['plugin_settings'] = plugin_settings
            cfg = FetcherConfig.from_submitted(data, capabilities)
            # Fields this engine cannot work without (an external browser with no endpoint has
            # nowhere to connect) - declared on the field via _needs(required=True).
            for name in FetcherConfig.required_fields(capabilities):
                if not getattr(cfg, name, None):
                    field = getattr(form, name, None)
                    message = gettext('This is required for this browser')
                    if field is not None:
                        field.errors.append(message)
                    else:
                        flash(message, 'error')
                    return None
            return cfg
        except ValidationError as e:
            for err in e.errors():
                loc = err['loc'][0] if err['loc'] else ''
                field = getattr(form, str(loc), None)
                if field is not None:
                    field.errors.append(err['msg'])
                else:
                    flash(err['msg'], 'error')
            return None

    @browser_config_blueprint.route("/browsers/add/<string:base_fetcher>", methods=['GET', 'POST'])
    @login_optionally_required
    def browser_config_add(base_fetcher):
        """Add a browser config *variation* based on a specific engine (from the row's link).
        The base is fixed by the URL, so the form's fields gate correctly for that engine."""
        if _browser_config_locked():
            flash(gettext("Browser configuration is locked on this instance"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        from changedetectionio import content_fetchers
        from changedetectionio.content_fetchers.base import FetcherCapabilities

        cls = getattr(content_fetchers, base_fetcher, None)
        caps = FetcherCapabilities.from_fetcher(cls)
        # Must be an engine that has something to configure (a browser, or the plain client).
        if cls is None or not caps.can_host_variation:
            flash(gettext("Unknown base browser"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        base_label = dict(content_fetchers.available_fetchers()).get(base_fetcher, base_fetcher)

        sections, form_class = _plugin_sections_and_form(base_fetcher, caps.model_dump())
        form = form_class(request.form if request.method == 'POST' else None)
        if request.method == 'POST' and form.validate():
            if _label_is_taken(form.label.data):
                form.label.errors.append(gettext("A browser with this name already exists"))
            else:
                cfg = _validate_and_build_config(form, caps, sections)
                if cfg is not None:
                    datastore.browser_config_store.add(
                        label=form.label.data,
                        base_fetcher=base_fetcher,
                        browser_config=cfg.model_dump(exclude_defaults=True),
                    )
                    return _saved(gettext("Browser added"))

        return _render_form(form, 'add', base_fetcher, base_label, sections, caps,
                            ('ui.browser_config.browser_config_add', {'base_fetcher': base_fetcher}))

    @browser_config_blueprint.route("/browsers/edit/<string:config_id>", methods=['GET', 'POST'])
    @login_optionally_required
    def browser_config_edit(config_id):
        if _browser_config_locked():
            flash(gettext("Browser configuration is locked on this instance"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        from changedetectionio.model.browser_config import list_builtin_browsers

        # Built-in engine browsers are editable too: their config is stored in browsers.json
        # keyed by the engine name (e.g. 'html_webdriver'), and the resolver picks it up when a
        # watch/global uses that engine. The engine is fixed (never user-choosable on edit).
        builtins = {b['id']: b for b in list_builtin_browsers()}
        is_builtin = config_id in builtins
        entry = datastore.browser_config_store.get(config_id)
        if not entry and not is_builtin:
            flash(gettext("Browser config not found"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))

        base = config_id if is_builtin else (entry or {}).get('base_fetcher')
        base_label = str(builtins[config_id]['label']) if is_builtin else base
        sections, form_class = _plugin_sections_and_form(base, _caps_for(base) if base else None)
        saved_plugin_settings = ((entry or {}).get('browser_config') or {}).get('plugin_settings') or {}

        if request.method == 'POST':
            form = form_class(request.form)
            if form.validate():
                if (not is_builtin) and _label_is_taken(form.label.data, exclude_id=config_id):
                    form.label.errors.append(gettext("A browser with this name already exists"))
                else:
                    cfg = _validate_and_build_config(form, _caps_for(base) if base else None,
                                                     sections, saved_plugin_settings)
                    if cfg is not None:
                        datastore.browser_config_store.upsert(
                            config_id,
                            label=(base_label if is_builtin else form.label.data),
                            base_fetcher=base,
                            browser_config=cfg.model_dump(exclude_defaults=True),
                        )
                        return _saved(gettext("Browser config updated"))
        else:
            form = form_class(data=_entry_to_formdata(entry, sections) if entry else {'label': base_label})

        return _render_form(form, 'edit', base, base_label, sections, _caps_for(base) if base else None,
                            ('ui.browser_config.browser_config_edit', {'config_id': config_id}),
                            config_id=config_id, is_builtin=is_builtin)

    @browser_config_blueprint.route("/browsers/remove/<string:config_id>", methods=['POST'])
    @login_optionally_required
    def browser_config_remove(config_id):
        if _browser_config_locked():
            flash(gettext("Browser configuration is locked on this instance"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        # A watch or group left pointing at a removed browser can't be checked any more
        # (BrowserConfigDoesntExist), so a browser that is still in use stays.
        from markupsafe import Markup
        from changedetectionio.model.browser_config import browser_config_usage
        if datastore.data['settings']['application'].get('fetch_backend') == config_id:
            flash(gettext("This is the default browser, choose another default before removing it"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        in_use = browser_config_usage(datastore).get(config_id)
        if in_use:
            # The link lists exactly the watches counted here (same watch_browser_ids() test)
            flash(Markup(gettext(
                'This browser is still in use (watches: %(watches)s, groups: %(groups)s), switch them to another browser before removing it - <a href="%(url)s">show its watches</a>',
                watches=in_use['watches'], groups=in_use['groups'],
                url=url_for('watchlist.index', browser=config_id))), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        if datastore.browser_config_store.delete(config_id):
            flash(gettext("Browser config removed"))
        else:
            flash(gettext("Browser config not found"), 'error')
        return redirect(url_for('ui.browser_config.browsers_overview'))

    @browser_config_blueprint.route("/browsers/set-default/<string:config_id>", methods=['POST'])
    @login_optionally_required
    def browser_config_set_default(config_id):
        # "Default browser" is the global settings.application.fetch_backend - the single source
        # of truth a watch/group set to 'system' resolves to. This /browsers tab is now the only
        # place it's set (the Settings page shows it read-only). Only usable (ready-to-use)
        # built-in engines or saved browser configs may be the default.
        from changedetectionio.model.browser_config import list_builtin_browsers
        builtins = {b['id'] for b in list_builtin_browsers()}
        if config_id in builtins or datastore.browser_config_store.get(config_id):
            datastore.data['settings']['application']['fetch_backend'] = config_id
            logger.debug(f"Default browser (settings.application.fetch_backend) set to '{config_id}'")
            flash(gettext("Default browser set"))
        else:
            flash(gettext("Browser config not found"), 'error')
        return redirect(url_for('ui.browser_config.browsers_overview'))

    return browser_config_blueprint
