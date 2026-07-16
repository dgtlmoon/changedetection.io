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
    """List of built-in engine 'browsers' with capabilities and any stored overrides.

    Each built-in may have a browsers.json entry keyed by the engine name (created when the
    user edits it); if so we surface its stored browser_config so the overview shows it.
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    out = []
    for name, description in content_fetchers.available_fetchers():
        caps = FetcherCapabilities.from_fetcher(getattr(content_fetchers, name, None))
        stored = datastore.browser_config_store.get(name) or {}
        out.append({
            'name': name,
            'description': description,
            'capabilities': caps.model_dump(),
            'browser_config': stored.get('browser_config') or {},
        })
    return out


def _caps_for(base_name):
    """Capability dict for an engine, so the form renders only the fields it can honour
    (e.g. html_requests has no screenshots -> no viewport/locale/timezone)."""
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    return FetcherCapabilities.from_fetcher(getattr(content_fetchers, base_name, None)).model_dump()


def _entry_to_formdata(entry):
    """Flatten a browsers.json entry into flat form field values."""
    data = {
        'label': entry.get('label'),
        'base_fetcher': entry.get('base_fetcher'),
    }
    data.update(entry.get('browser_config') or {})
    return data


def construct_blueprint(datastore: ChangeDetectionStore):
    browser_config_blueprint = Blueprint('browser_config', __name__, template_folder="templates")

    def _render_overview(add_form=None, open_add_form=False):
        from .form_browseroptions import BrowserOptionsForm
        if add_form is None:
            add_form = BrowserOptionsForm()
        # A browser config only makes sense if a browser-capable engine exists; the form's
        # base_fetcher choices are already filtered to those, so an empty list => none.
        browser_engine_available = bool(add_form.base_fetcher.choices)
        # Gate the add form's fields by its selected (default first) base engine's capabilities.
        add_base = add_form.base_fetcher.data or (add_form.base_fetcher.choices[0][0]
                                                  if add_form.base_fetcher.choices else None)
        return render_template(
            "browsers-overview.html",
            base_fetchers=_base_fetchers(datastore),
            browser_configs=datastore.browser_config_store.all(),
            add_form=add_form,
            open_add_form=open_add_form,
            browser_engine_available=browser_engine_available,
            # The default browser is the global system fetch_backend (single source of truth).
            default_browser_id=datastore.data['settings']['application'].get('fetch_backend'),
            caps=_caps_for(add_base) if add_base else {},
        )

    @browser_config_blueprint.route("/browsers", methods=['GET'])
    @login_optionally_required
    def browsers_overview():
        return _render_overview()

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

    @browser_config_blueprint.route("/browsers/add", methods=['GET', 'POST'])
    @login_optionally_required
    def browser_config_add():
        from .form_browseroptions import BrowserOptionsForm
        # The add form lives inline on the overview page; a bare GET just goes there.
        if request.method == 'GET':
            return redirect(url_for('ui.browser_config.browsers_overview'))

        form = BrowserOptionsForm(request.form)
        if form.validate():
            if _label_is_taken(form.label.data):
                form.label.errors.append(gettext("A browser with this name already exists"))
            else:
                cfg = _validate_and_build_config(form)
                if cfg is not None:
                    datastore.browser_config_store.add(
                        label=form.label.data,
                        base_fetcher=form.base_fetcher.data,
                        browser_config=cfg.model_dump(exclude_defaults=True),
                    )
                    flash(gettext("Browser added"))
                    return redirect(url_for('ui.browser_config.browsers_overview'))

        # Invalid - re-render the overview with the form open and errors shown inline.
        return _render_overview(add_form=form, open_add_form=True)

    @browser_config_blueprint.route("/browsers/edit/<string:config_id>", methods=['GET', 'POST'])
    @login_optionally_required
    def browser_config_edit(config_id):
        from .form_browseroptions import BrowserOptionsForm
        from changedetectionio.model.browser_config import list_builtin_browsers

        # Built-in engine browsers are editable too: their config is stored in browsers.json
        # keyed by the engine name (e.g. 'html_webdriver'), and the resolver picks it up when a
        # watch/global uses that engine. The engine is fixed (base_fetcher == the id).
        builtins = {b['id']: b for b in list_builtin_browsers()}
        is_builtin = config_id in builtins
        entry = datastore.browser_config_store.get(config_id)
        if not entry and not is_builtin:
            flash(gettext("Browser config not found"), 'error')
            return redirect(url_for('ui.browser_config.browsers_overview'))

        if request.method == 'POST':
            form = BrowserOptionsForm(request.form)
            if is_builtin:
                # Lock the engine to this built-in; the label is fixed too.
                form.base_fetcher.choices = [(config_id, builtins[config_id]['label'])]
            if form.validate():
                if (not is_builtin) and _label_is_taken(form.label.data, exclude_id=config_id):
                    form.label.errors.append(gettext("A browser with this name already exists"))
                else:
                    cfg = _validate_and_build_config(form)
                    if cfg is not None:
                        base = config_id if is_builtin else form.base_fetcher.data
                        datastore.browser_config_store.upsert(
                            config_id,
                            # built-in labels come from lazy_gettext - coerce to a plain str for storage
                            label=(str(builtins[config_id]['label']) if is_builtin else form.label.data),
                            base_fetcher=base,
                            browser_config=cfg.model_dump(exclude_defaults=True),
                        )
                        flash(gettext("Browser config updated"))
                        return redirect(url_for('ui.browser_config.browsers_overview'))
        else:
            if entry:
                form = BrowserOptionsForm(data=_entry_to_formdata(entry))
            else:
                # Built-in with no overrides yet - prefill with its identity.
                form = BrowserOptionsForm(data={'label': builtins[config_id]['label'], 'base_fetcher': config_id})
            if is_builtin:
                form.base_fetcher.choices = [(config_id, builtins[config_id]['label'])]

        edit_base = config_id if is_builtin else ((entry or {}).get('base_fetcher') or form.base_fetcher.data)
        return render_template("browser-config-edit.html", form=form, mode='edit',
                               config_id=config_id, is_builtin=is_builtin,
                               caps=_caps_for(edit_base) if edit_base else {})

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
