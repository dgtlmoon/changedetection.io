"""
Browsers blueprint - manage named browser configs ("profiles").

Lists the available base content fetchers (engines) with their capabilities, and lets the
user add / edit / remove / set-default browser configs, persisted in browsers.json via
datastore.browser_config_store.

Registered as a sub-blueprint of `ui`, so endpoints are `ui.browser_config.*`.
"""
from flask import Blueprint, request, render_template, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger
from pydantic import ValidationError

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def _base_fetchers(datastore):
    """Browser-capable base engines shown as rows - each offers "Add variation" to create a
    config based on it. Includes base-only engines (e.g. html_playwright_builtin); `ready_to_use`
    tells the template which extra actions apply (Edit / Make default only for ready-to-use ones).
    A ready-to-use engine may have a stored built-in override config (keyed by the engine name).
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    out = []
    for name, description in content_fetchers.available_fetchers():
        cls = getattr(content_fetchers, name, None)
        caps = FetcherCapabilities.from_fetcher(cls)
        # Only browsers (support screenshots / visual-selector) are configurable base rows.
        if not (caps.supports_screenshots or caps.supports_xpath_element_data):
            continue
        stored = datastore.browser_config_store.get(name) or {}
        out.append({
            'name': name,
            'description': description,
            'capabilities': caps.model_dump(),
            'browser_config': stored.get('browser_config') or {},
            'ready_to_use': getattr(cls, 'ready_to_use', True),
        })
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


def _entry_to_formdata(entry):
    """Flatten a browsers.json entry into flat form field values (base is contextual, not a field)."""
    data = {'label': entry.get('label')}
    data.update(entry.get('browser_config') or {})
    return data


def construct_blueprint(datastore: ChangeDetectionStore):
    browser_config_blueprint = Blueprint('browser_config', __name__, template_folder="templates")

    @browser_config_blueprint.route("/browsers", methods=['GET'])
    @login_optionally_required
    def browsers_overview():
        return render_template(
            "browsers-overview.html",
            base_fetchers=_base_fetchers(datastore),
            browser_configs=datastore.browser_config_store.all(),
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

    def _validate_and_build_config(form):
        """Return a validated FetcherConfig, or None (with errors attached to form)."""
        from changedetectionio.model.browser_config import FetcherConfig
        try:
            return FetcherConfig(**form.to_fetcher_config_dict())
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
        from .form_browseroptions import BrowserOptionsForm
        from changedetectionio import content_fetchers
        from changedetectionio.content_fetchers.base import FetcherCapabilities

        cls = getattr(content_fetchers, base_fetcher, None)
        caps = FetcherCapabilities.from_fetcher(cls)
        # Must be a real browser-capable engine
        if cls is None or not (caps.supports_screenshots or caps.supports_xpath_element_data):
            flash(gettext("Unknown base browser"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))
        base_label = dict(content_fetchers.available_fetchers()).get(base_fetcher, base_fetcher)

        form = BrowserOptionsForm(request.form if request.method == 'POST' else None)
        if request.method == 'POST' and form.validate():
            if _label_is_taken(form.label.data):
                form.label.errors.append(gettext("A browser with this name already exists"))
            else:
                cfg = _validate_and_build_config(form)
                if cfg is not None:
                    datastore.browser_config_store.add(
                        label=form.label.data,
                        base_fetcher=base_fetcher,
                        browser_config=cfg.model_dump(exclude_defaults=True),
                    )
                    flash(gettext("Browser added"))
                    return redirect(url_for('ui.browser_config.browsers_overview'))

        locale_choices, timezone_choices = _autocomplete_choices()
        return render_template("browser-config-form.html", form=form, mode='add',
                               base_fetcher=base_fetcher, base_label=base_label, caps=caps.model_dump(),
                               locale_choices=locale_choices, timezone_choices=timezone_choices,
                               form_action=url_for('ui.browser_config.browser_config_add', base_fetcher=base_fetcher))

    @browser_config_blueprint.route("/browsers/edit/<string:config_id>", methods=['GET', 'POST'])
    @login_optionally_required
    def browser_config_edit(config_id):
        from .form_browseroptions import BrowserOptionsForm
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

        if request.method == 'POST':
            form = BrowserOptionsForm(request.form)
            if form.validate():
                if (not is_builtin) and _label_is_taken(form.label.data, exclude_id=config_id):
                    form.label.errors.append(gettext("A browser with this name already exists"))
                else:
                    cfg = _validate_and_build_config(form)
                    if cfg is not None:
                        datastore.browser_config_store.upsert(
                            config_id,
                            label=(base_label if is_builtin else form.label.data),
                            base_fetcher=base,
                            browser_config=cfg.model_dump(exclude_defaults=True),
                        )
                        flash(gettext("Browser config updated"))
                        return redirect(url_for('ui.browser_config.browsers_overview'))
        else:
            form = BrowserOptionsForm(data=_entry_to_formdata(entry) if entry else {'label': base_label})

        locale_choices, timezone_choices = _autocomplete_choices()
        return render_template("browser-config-form.html", form=form, mode='edit',
                               config_id=config_id, is_builtin=is_builtin,
                               base_fetcher=base, base_label=base_label,
                               caps=_caps_for(base) if base else {},
                               locale_choices=locale_choices, timezone_choices=timezone_choices,
                               form_action=url_for('ui.browser_config.browser_config_edit', config_id=config_id))

    @browser_config_blueprint.route("/browsers/remove/<string:config_id>", methods=['POST'])
    @login_optionally_required
    def browser_config_remove(config_id):
        if datastore.browser_config_store.delete(config_id):
            flash(gettext("Browser config removed"))
        else:
            flash(gettext("Browser config not found"), 'error')
        return redirect(url_for('ui.browser_config.browsers_overview'))

    @browser_config_blueprint.route("/browsers/set-default/<string:config_id>", methods=['POST'])
    @login_optionally_required
    def browser_config_set_default(config_id):
        # "Default" is the global system fetch_backend - the single source of truth that a
        # watch/group set to 'system' resolves to. This is settable from here or from Settings.
        from changedetectionio.model.browser_config import list_builtin_browsers
        builtins = {b['id'] for b in list_builtin_browsers()}
        if config_id in builtins or datastore.browser_config_store.get(config_id):
            datastore.data['settings']['application']['fetch_backend'] = config_id
            flash(gettext("Default browser set"))
        else:
            flash(gettext("Browser config not found"), 'error')
        return redirect(url_for('ui.browser_config.browsers_overview'))

    return browser_config_blueprint
