import os

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required

# Checkboxes llm-settings_llm.html shows only in some states. An unticked checkbox posts nothing, and WTForms reads
# a missing one as False, so a save from a page that didn't show the checkbox would switch its setting off
SHOWN_ONLY_WITH_A_MODEL = ('override_diff_with_summary', 'restock_use_fallback_extract')
SHOWN_ONLY_WITHOUT_ENV_CONFIG = ('local_thinking_off', 'debug')


def save_llm_form(datastore, llm_form_data):
    """Merge the submitted AI / LLM form over the stored settings (settings.application.llm)."""
    from changedetectionio.llm.evaluator import get_llm_config, llm_configured_via_env
    from changedetectionio.model.LLMSettings import LLMSettings

    # LLM config lives under settings.application.llm.* (post update_31).
    # Hydrate the stored dict into LLMSettings, then merge form input over it.
    # WTForms field names match LLMSettings field names exactly, so both sides
    # of the merge use the same key shape.
    existing_llm = LLMSettings.model_validate(
        datastore.data['settings']['application'].get('llm') or {}
    )

    llm_form_input = dict(llm_form_data or {})

    # Empty IntegerField submissions come back as None from WTForms;
    # the schema declares those fields as strict `int`, so passing
    # them through would fail validation. Treat None like the
    # absent-key case: keep the stored value, don't merge.
    llm_form_input = {k: v for k, v in llm_form_input.items() if v is not None}

    # Checkboxes the page didn't show keep their stored value. The page was drawn from the settings as stored, so
    # check the same conditions against those (e.g. no model yet after "Remove provider", then a new one is saved)
    not_shown = []
    if not (get_llm_config(datastore) or {}).get('model'):
        not_shown += SHOWN_ONLY_WITH_A_MODEL
    if llm_configured_via_env():
        not_shown += SHOWN_ONLY_WITHOUT_ENV_CONFIG
    for name in not_shown:
        llm_form_input.pop(name, None)

    # PasswordField never re-renders, so a blank submitted value means
    # "keep stored key" — drop it from the merge.
    if not (llm_form_input.get('api_key') or '').strip():
        llm_form_input.pop('api_key', None)

    # Env-var overrides make these fields read-only in the UI — ignore form input.
    if os.getenv('LLM_TOKEN_BUDGET_MONTH', '').strip():
        llm_form_input.pop('token_budget_month', None)
    if os.getenv('LLM_MAX_INPUT_CHARS', '').strip():
        llm_form_input.pop('max_input_chars', None)

    # System-managed counters must never come from the form.
    for protected in LLMSettings.PROTECTED_FIELDS:
        llm_form_input.pop(protected, None)

    merged = LLMSettings.model_validate({**existing_llm.model_dump(), **llm_form_input})

    # Clearing the model field strips only the provider-connection fields.
    # User toggles, budgets, prompts and system counters survive (matches /llm/clear).
    exclude = set(LLMSettings.CONNECTION_FIELDS) if not merged.model.strip() else None
    datastore.data['settings']['application']['llm'] = merged.model_dump(exclude=exclude)


def llm_template_context(datastore):
    """What the "AI / LLM" part (llm-settings_llm.html) needs, besides the form."""
    from changedetectionio.llm.evaluator import (
        _get_max_input_chars,
        get_global_token_budget_month,
        get_llm_config,
        llm_configured_via_env,
    )
    llm_config = get_llm_config(datastore) or {}
    llm_env_configured = llm_configured_via_env()
    _max_input_chars_env_str = os.getenv('LLM_MAX_INPUT_CHARS', '').strip()
    return dict(
        llm_config=llm_config,
        llm_env_configured=llm_env_configured,
        # Once a key is stored, the provider and the key itself are locked and can only be
        # cleared with "Remove provider". The key field renders blank so that an untouched
        # save preserves it, which makes any stray value in it - a browser autofill, a bad
        # paste - silently overwrite a working key on the next Save, with no copy kept
        # anywhere to recover from. Disabling the input takes it out of the POST entirely;
        # the form is seeded with data=default, so an absent field falls back to the stored
        # value and the merge is a no-op for it.
        llm_provider_locked=bool(llm_config.get('api_key')) and not llm_env_configured,
        llm_stored=datastore.data['settings']['application'].get('llm') or {},
        llm_token_budget_month=get_global_token_budget_month(datastore),
        llm_token_budget_month_env=get_global_token_budget_month(),  # env var only, for readonly logic
        llm_max_input_chars_env=int(_max_input_chars_env_str) if _max_input_chars_env_str.isdigit() else 0,
        llm_effective_max_input_chars=_get_max_input_chars(datastore),
        # Cost display: only when user configured their own key (not hosted/operator-managed)
        llm_show_costs=not llm_env_configured,
    )


def mcp_template_context(datastore):
    """What the "MCP Server" part (llm-settings_mcp.html) needs."""
    from changedetectionio import forms
    from changedetectionio.blueprint.mcp import is_mcp_disabled

    app_settings = datastore.data['settings']['application']
    mcp_disabled = is_mcp_disabled()
    mcp_url = None
    if not mcp_disabled:
        # The same address OAuth uses: the "Public MCP address" setting, otherwise built from this request, which
        # already includes the X-Forwarded-Prefix/Host/Proto of a reverse proxy (USE_X_SETTINGS)
        from changedetectionio.blueprint.mcp.oauth import resource
        mcp_url = resource(datastore)
    from changedetectionio.blueprint.mcp import INSTRUCTIONS
    return dict(
        mcp_disabled=mcp_disabled,
        mcp_url=mcp_url,
        # What the address is when the setting is empty, shown as its placeholder
        mcp_request_address=request.url_root.rstrip('/'),
        mcp_builtin_note=INSTRUCTIONS,
        mcp_anonymous_calls_per_minute=anonymous_calls_per_minute(),
        token_form=mcp_token_form(datastore),
        **mcp_tokens_context(datastore),
        **mcp_oauth_context(datastore),
    )


def anonymous_calls_per_minute():
    from changedetectionio.blueprint.mcp import ANONYMOUS_CALLS_PER_MINUTE_DEFAULT
    try:
        return int(os.getenv('MCP_ANONYMOUS_CALLS_PER_MINUTE', ANONYMOUS_CALLS_PER_MINUTE_DEFAULT))
    except ValueError:
        return ANONYMOUS_CALLS_PER_MINUTE_DEFAULT


def mcp_token_form(datastore, formdata=None):
    """The add / edit token form, its group checkboxes being the tags that exist now, plus a perm_<row> field for each
    permission row a plugin added (register_mcp_permission_rows), listed in form.plugin_rows for the grid."""
    from flask_babel import lazy_gettext as _l
    from wtforms import RadioField
    from changedetectionio import forms
    from changedetectionio.blueprint.mcp.tools import plugin_permission_rows
    rows = plugin_permission_rows()
    form_class = forms.MCPTokenForm
    if rows:
        level_labels = {'none': _l('None'), 'read': _l('Read'), 'write': _l('Write')}
        form_class = type('MCPTokenFormWithPluginRows', (forms.MCPTokenForm,), {
            f'perm_{name}': RadioField(row['label'], default='none',
                                       choices=[(level, level_labels[level]) for level in row['levels']])
            for name, row in rows.items()})
    form = form_class(formdata=formdata)
    form.plugin_rows = [(form[f'perm_{name}'], row['description']) for name, row in rows.items()]
    tags = datastore.data['settings']['application'].get('tags') or {}
    form.tags.choices = sorted(((uuid, t.get('title') or uuid) for uuid, t in tags.items()), key=lambda c: c[1].lower())
    return form


def mcp_oauth_context(datastore):
    """What the OAuth sub-tab (_mcp-oauth-grants.html) needs: the assistants signed in with OAuth, and whether sign-in
    is offered at all (it needs MCP on and a password, blueprint/mcp/oauth)."""
    from changedetectionio.blueprint.mcp import oauth
    from changedetectionio.blueprint.mcp.oauth.store import grants
    from changedetectionio.blueprint.mcp.tools import permissions
    all_tags = datastore.data['settings']['application'].get('tags') or {}
    listed = [dict(grant, id=grant_id, levels=permissions(grant.get('permissions')),
                   group_names=[all_tags[t].get('title') for t in grant.get('tags') or [] if t in all_tags])
              for grant_id, grant in grants(datastore.data['settings']['application']).items()]
    listed.sort(key=lambda t: t.get('created') or 0)
    return dict(mcp_oauth_grants=listed, mcp_oauth_available=oauth.oauth_available(datastore),
                mcp_password_set=oauth.password_set(datastore))


def mcp_tokens_context(datastore):
    """What the access token list (_mcp-tokens.html) needs, also rendered on its own after every ajax change."""
    from changedetectionio.blueprint.mcp.tools import permissions, plugin_permission_rows
    tokens = datastore.data['settings']['application'].get('mcp_tokens') or {}
    all_tags = datastore.data['settings']['application'].get('tags') or {}
    listed = [dict(token, id=token_id, levels=permissions(token.get('permissions')),
                   tags=[t for t in token.get('tags') or []],
                   group_names=[all_tags[t].get('title') for t in token.get('tags') or [] if t in all_tags])
              for token_id, token in tokens.items()]
    listed.sort(key=lambda t: t.get('created') or 0)
    return dict(mcp_tokens=listed, mcp_enabled=bool(datastore.data['settings']['application'].get('mcp_enabled')),
                mcp_plugin_area_labels={name: row['label'] for name, row in plugin_permission_rows().items()})


# Sent as the API key when the connection test goes to an address that isn't the saved one and no key is saved:
# keyless servers (Ollama, most local OpenAI-compatible ones) ignore it, and it keeps litellm from using a key from
# the environment instead
NO_KEY_PLACEHOLDER = 'no-key'


def construct_llm_blueprint(datastore: ChangeDetectionStore):
    llm_blueprint = Blueprint('llm', __name__, template_folder="templates")

    def get_plugin_settings_tabs():
        # For the /settings tab row these pages show (settings-tabs.html), so plugin tabs are listed there too
        from changedetectionio.pluggy_interface import get_plugin_settings_tabs
        return get_plugin_settings_tabs()

    # Linked from the "AI / LLM / MCP" tab on /settings (blueprint/settings/templates/settings.html)

    # Two tabs, each its own page and route (not #anchors), so each tab's form stands alone:
    #   /settings/ai/llm - the "AI / LLM" tab (the default), /settings/ai/mcp - the "MCP Server" tab
    @llm_blueprint.route("", methods=['GET'], strict_slashes=False)
    @login_optionally_required
    def ai_settings_index():
        return redirect(url_for('settings.llm.llm_settings_page'))

    @llm_blueprint.route("/llm", methods=['GET', 'POST'])
    @login_optionally_required
    def llm_settings_page():
        """The AI / LLM settings page, moved out of /settings. Stored in settings.application.llm as before."""
        from changedetectionio import forms
        from changedetectionio.llm.evaluator import is_llm_features_disabled
        from changedetectionio.model.LLMSettings import LLMSettings

        # Not registered at all when LLM_FEATURES_DISABLED is set at startup, and refused if it's set later
        if is_llm_features_disabled():
            abort(404)

        # api_key is intentionally blanked on GET — PasswordField never re-renders
        # its value, and a blank submission preserves the stored key.
        default_llm = LLMSettings.model_validate(datastore.data['settings']['application'].get('llm') or {}).model_dump()
        default_llm['api_key'] = ''
        form = forms.globalLLMSettingsPageForm(formdata=request.form if request.method == 'POST' else None,
                                               data={'llm': default_llm})

        if request.method == 'POST':
            if form.validate():
                save_llm_form(datastore, form.data.get('llm'))
                datastore.commit()
                # AI settings change how checks are evaluated, so reprocess everything (as a /settings save does)
                datastore.clear_all_last_checksums()
                flash(gettext("Settings updated."))
                return redirect(url_for('settings.llm.llm_settings_page'))
            flash(gettext("An error occurred, please see below."), "error")

        return render_template("llm-settings.html", form=form, active_tab='llm', plugin_tabs=get_plugin_settings_tabs(),
                               **llm_template_context(datastore))

    @llm_blueprint.route("/mcp", methods=['GET', 'POST'])
    @login_optionally_required
    def mcp_settings_page():
        """The "MCP Server" tab: the on/off switch, the address, the access tokens and how to connect assistants."""
        from changedetectionio import forms
        from changedetectionio.llm.evaluator import is_llm_features_disabled
        if is_llm_features_disabled():
            abort(404)
        app_settings = datastore.data['settings']['application']
        form = forms.globalMCPSettingsPageForm(formdata=request.form if request.method == 'POST' else None,
                                               data={'enabled': bool(app_settings.get('mcp_enabled')),
                                                     'note': app_settings.get('mcp_note') or '',
                                                     'anonymous_read': bool(app_settings.get('mcp_anonymous_read')),
                                                     'public_url': app_settings.get('mcp_base_url') or ''})
        if request.method == 'POST' and form.validate():
            was_enabled = bool(app_settings.get('mcp_enabled'))
            enabled = bool(form.enabled.data)
            app_settings['mcp_enabled'] = enabled
            # Line endings as the browser sends them (\r\n) would reach the assistant as they are
            app_settings['mcp_note'] = (form.note.data or '').replace('\r\n', '\n').strip()
            app_settings['mcp_anonymous_read'] = bool(form.anonymous_read.data)
            # The OAuth issuer: grants are bound to {address}/mcp/v1, so a new address signs every connection out
            public_url = forms.normalise_mcp_public_url(form.public_url.data)
            address_changed = public_url != (app_settings.get('mcp_base_url') or '')
            app_settings['mcp_base_url'] = public_url
            if enabled == was_enabled:
                message = gettext("MCP settings saved.")
            elif enabled:
                message = gettext("MCP server switched on.")
            else:
                message = gettext("MCP server switched off.")
            datastore.commit()
            flash(message, 'notice')
            if address_changed and (app_settings.get('mcp_oauth') or {}).get('grants'):
                flash(gettext("The public MCP address changed: assistants connected with sign-in (OAuth) need to connect again."), 'notice')
            return redirect(url_for('settings.llm.mcp_settings_page'))
        return render_template("llm-settings.html", form=form, active_tab='mcp', plugin_tabs=get_plugin_settings_tabs(),
                               **mcp_template_context(datastore))

    # The access tokens, managed from the overlay on the "Access tokens" sub-tab with ajax. Every change answers with
    # the re-rendered list, which the page swaps in. POST only, with the CSRF token in the X-CSRFToken header (csrf.js)

    def mcp_tokens_html():
        """The token list and Overview's status, both depend on the tokens."""
        context = mcp_tokens_context(datastore)
        return {'html': render_template("_mcp-tokens.html", **context),
                'overview_html': render_template("_mcp-overview-status.html", **context)}

    def mcp_ai_enabled_or_404():
        from changedetectionio.llm.evaluator import is_llm_features_disabled
        if is_llm_features_disabled():
            abort(404)

    def mcp_token_or_404(token_id):
        mcp_ai_enabled_or_404()
        token = (datastore.data['settings']['application'].get('mcp_tokens') or {}).get(token_id)
        if not token:
            abort(404)
        return token

    def mcp_token_form_errors(form):
        return jsonify({'errors': {name: [str(e) for e in errors] for name, errors in form.errors.items()}}), 400

    def mcp_token_permissions(form):
        from changedetectionio.blueprint.mcp.tools import permission_defaults
        return {area: form[f'perm_{area}'].data for area in permission_defaults()}

    @llm_blueprint.route("/mcp/tokens", methods=['GET'])
    @login_optionally_required
    def mcp_tokens_list():
        mcp_ai_enabled_or_404()
        return mcp_tokens_html()['html']

    @llm_blueprint.route("/mcp/tokens", methods=['POST'])
    @login_optionally_required
    def mcp_token_add():
        """A new access token. The token itself is in this answer only, it's stored hashed."""
        from changedetectionio.blueprint.mcp.tokens import add_token
        mcp_ai_enabled_or_404()
        form = mcp_token_form(datastore, request.form)
        if not form.validate():
            return mcp_token_form_errors(form)
        token_id, token = add_token(datastore.data['settings']['application'], form.name.data.strip(),
                                    mcp_token_permissions(form), form.tags.data)
        datastore.commit()
        return jsonify({'id': token_id, 'token': token, **mcp_tokens_html()})

    @llm_blueprint.route("/mcp/tokens/<string:token_id>", methods=['POST'])
    @login_optionally_required
    def mcp_token_update(token_id):
        """A token's new name, permissions and groups, the token itself stays the same."""
        token = mcp_token_or_404(token_id)
        form = mcp_token_form(datastore, request.form)
        if not form.validate():
            return mcp_token_form_errors(form)
        token['name'] = form.name.data.strip()
        token['permissions'] = mcp_token_permissions(form)
        token['tags'] = list(form.tags.data or [])
        datastore.commit()
        return jsonify({'id': token_id, **mcp_tokens_html()})

    @llm_blueprint.route("/mcp/tokens/<string:token_id>/revoke", methods=['POST'])
    @login_optionally_required
    def mcp_token_revoke(token_id):
        """The token stops working at once; the assistant using it has to be given a new one."""
        mcp_token_or_404(token_id)
        del datastore.data['settings']['application']['mcp_tokens'][token_id]
        datastore.commit()
        return jsonify(mcp_tokens_html())

    @llm_blueprint.route("/mcp/oauth/<string:grant_id>/revoke", methods=['POST'])
    @login_optionally_required
    def mcp_oauth_revoke(grant_id):
        """An assistant signed in with OAuth loses access at once (both its tokens); it can sign in again."""
        from changedetectionio.blueprint.mcp.oauth.store import revoke
        mcp_ai_enabled_or_404()
        if not revoke(datastore.data['settings']['application'], grant_id):
            abort(404)
        datastore.commit()
        return jsonify({'html': render_template("_mcp-oauth-grants.html", **mcp_oauth_context(datastore))})

    @llm_blueprint.route("/llm/models", methods=['GET'])
    @login_optionally_required
    def llm_get_models():
        from flask import request
        from changedetectionio.validate_url import is_llm_api_base_safe
        provider = request.args.get('provider', '').strip()
        api_key  = request.args.get('api_key',  '').strip()
        api_base = request.args.get('api_base', '').strip()

        logger.debug(f"LLM model list requested for provider={provider!r} api_base={api_base!r}")

        if not provider:
            logger.debug("LLM model list: no provider specified, returning 400")
            return jsonify({'models': [], 'error': 'No provider specified'}), 400

        ok, reason = is_llm_api_base_safe(api_base)
        if not ok:
            logger.warning(f"LLM model list refused: api_base failed SSRF check ({reason})")
            return jsonify({'models': [], 'error': reason}), 400

        # Credential-exfiltration guard (GHSA-g36r-fm2p-87xm).
        # Only substitute the stored api_key when api_base matches the stored
        # api_base. If the caller pointed at a different destination, refuse —
        # otherwise a CSRF / unauthenticated request can ship the operator's
        # long-lived provider key (sent as Authorization: Bearer …) to an
        # attacker-controlled URL.
        stored_llm     = datastore.data['settings']['application'].get('llm') or {}
        stored_api_base = (stored_llm.get('api_base') or '').strip()
        if not api_key:
            if api_base == stored_api_base:
                api_key = (stored_llm.get('api_key') or '')
                logger.debug("LLM model list: no api_key in request, using stored key (api_base matches saved)")
            elif api_base and (stored_llm.get('api_key') or '').strip():
                logger.warning("LLM model list refused: api_base differs from saved config but no api_key supplied")
                return jsonify({'models': [], 'error': gettext(
                    "api_key is required when api_base differs from the saved configuration. "
                    "Refusing to send the stored API key to a different endpoint."
                )}), 400

        # Plain HTTP, not litellm.get_valid_models() - browsing the model list must not
        # pull ~200MB of litellm into the process before AI is even configured.
        from changedetectionio.llm.model_list import list_models, ModelListError
        try:
            models = list_models(provider, api_key=api_key, api_base=api_base)
        except ModelListError as e:
            logger.debug(f"LLM model list: provider={provider!r} refused or unreachable: {e}")
            return jsonify({'models': [], 'error': str(e)}), 400
        except Exception as e:
            logger.error(f"LLM model list failed for provider={provider!r}: {e}")
            logger.exception("LLM model list full traceback:")
            return jsonify({'models': [], 'error': str(e)}), 400

        logger.debug(f"LLM model list: got {len(models)} models for provider={provider!r}")
        return jsonify({'models': models, 'error': None})

    @llm_blueprint.route("/llm/test", methods=['POST'])
    @login_optionally_required
    def llm_test():
        from flask import request
        from changedetectionio.llm.client import completion_isolated
        from changedetectionio.validate_url import is_llm_api_base_safe

        # Pull stored config as the fallback, then override with anything the
        # form-driven JS sent as query params. Lets users test config changes
        # without first hitting Save (matching how /settings/ai/llm/models works).
        stored = datastore.data['settings']['application'].get('llm') or {}
        # Keep the raw request-supplied values around so we can detect whether
        # the caller explicitly steered api_base / api_key (credential-exfil guard below).
        req_api_key  = (request.args.get('api_key')  or '').strip()
        req_api_base = (request.args.get('api_base') or '').strip()
        stored_api_base = (stored.get('api_base') or '').strip()
        llm_cfg = {
            'model':                   (request.args.get('model')                   or stored.get('model', '')).strip(),
            'api_key':                 (req_api_key  or stored.get('api_key', '')).strip(),
            'api_base':                (req_api_base or stored_api_base).strip(),
            'provider_kind':           (request.args.get('provider_kind')           or stored.get('provider_kind', '')).strip(),
            'local_token_multiplier':   request.args.get('local_token_multiplier')  or stored.get('local_token_multiplier'),
        }
        model    = llm_cfg['model']
        api_base = llm_cfg['api_base']

        logger.debug(
            f"LLM connection test requested: model={model!r} api_base={api_base!r} "
            f"provider_kind={llm_cfg['provider_kind']!r} "
            f"source={'form' if request.args.get('model') else 'datastore'}"
        )

        if not model:
            logger.error("LLM connection test failed: no model configured")
            return jsonify({'ok': False, 'error': 'No model configured.'}), 400

        ok, reason = is_llm_api_base_safe(api_base)
        if not ok:
            logger.warning(f"LLM connection test refused: api_base failed SSRF check ({reason})")
            return jsonify({'ok': False, 'error': reason}), 400

        # Credential-exfiltration guard (GHSA-g36r-fm2p-87xm).
        # If the caller specified an api_base that differs from the saved one but
        # did NOT supply a matching api_key, refuse to substitute the stored key.
        # Otherwise a CSRF / unauthenticated request can route the operator's
        # long-lived provider key to an attacker-controlled endpoint.
        if req_api_base and req_api_base != stored_api_base and not req_api_key:
            if (stored.get('api_key') or '').strip():
                logger.warning("LLM connection test refused: api_base differs from saved config but no api_key supplied")
                return jsonify({'ok': False, 'error': gettext(
                    "api_key is required when api_base differs from the saved configuration. "
                    "Refusing to send the stored API key to a different endpoint."
                )}), 400
            # No key saved, so none to leak: e.g. a local Ollama tried before Save. Send a placeholder rather than no
            # key, or litellm falls back to a provider key from the environment (OPENAI_API_KEY...) and sends that
            llm_cfg['api_key'] = NO_KEY_PLACEHOLDER

        try:
            logger.debug(f"LLM connection test: sending test prompt to model={model!r}")
            # Reuse the same multiplier path the production calls use, so cloud providers
            # stay on a small base cap (matching upstream's pre-existing behavior) and only
            # reasoning-capable endpoints (Ollama, openai_compatible) opt into the extra
            # headroom needed for chain-of-thought to complete.
            # Timeout: resolve it the same way production calls do — cloud gets
            # DEFAULT_TIMEOUT (300s, tunable via LLM_TIMEOUT), and local/self-hosted
            # endpoints (IANA-restricted api_base) get the relaxed 1800s local cap so
            # a cold-starting or slow-prefilling local model doesn't falsely fail the
            # test even though the same call would succeed in production (issue #4225).
            from changedetectionio.llm.evaluator import apply_local_token_multiplier, get_llm_settings, resolve_llm_timeout
            # Isolated: trying a provider from the settings page must not leave ~200MB of
            # litellm resident in this process (it runs in-process if already loaded).
            text, total_tokens, input_tokens, output_tokens = completion_isolated(
                model=model,
                messages=[{'role': 'user', 'content':
                    'Respond with just the word: ready'}],
                api_key=llm_cfg.get('api_key') or None,
                api_base=api_base or None,
                timeout=resolve_llm_timeout(llm_cfg),
                max_tokens=apply_local_token_multiplier(200, llm_cfg),
                debug=get_llm_settings(datastore).debug,
            )
            reply = text.strip()
            if not reply:
                logger.warning(
                    f"LLM connection test: model={model!r} responded but returned empty content "
                    f"tokens={total_tokens} (in={input_tokens} out={output_tokens}) — "
                    f"check finish_reason in client debug log above"
                )
                return jsonify({'ok': False, 'error': 'Model responded but returned empty content — check server logs.'}), 400

            logger.success(
                f"LLM connection test OK: model={model!r} "
                f"tokens={total_tokens} (in={input_tokens} out={output_tokens}) "
                f"reply={reply!r}"
            )
            return jsonify({'ok': True, 'text': reply, 'tokens': total_tokens})

        except Exception as e:
            logger.error(f"LLM connection test FAILED: model={model!r} api_base={api_base!r} error={e}")
            logger.exception("LLM connection test full traceback:")
            return jsonify({'ok': False, 'error': str(e)}), 400

    # Both clear endpoints accept POST only — GET would let an attacker fire them via
    # <img src="...">, wiping LLM configuration / cached summaries on a logged-in
    # operator's browser (GHSA-g36r-fm2p-87xm). Flask-WTF CSRFProtect enforces a
    # CSRF token on POST automatically; the template renders csrf_token() inside the
    # surrounding <form>.
    @llm_blueprint.route("/llm/clear", methods=['POST'])
    @login_optionally_required
    def llm_clear():
        from changedetectionio.model.LLMSettings import LLMSettings
        logger.debug("LLM configuration cleared by user")
        # Read existing config, write back a dict that omits the connection fields —
        # so the saved dict no longer has model/api_key/api_base/etc.
        # Toggles, prompts, budgets and counters survive.
        settings = LLMSettings.model_validate(
            datastore.data['settings']['application'].get('llm') or {}
        )
        datastore.data['settings']['application']['llm'] = settings.model_dump(
            exclude=set(LLMSettings.CONNECTION_FIELDS)
        )
        datastore.commit()
        flash(gettext("AI / LLM configuration removed."), 'notice')
        return redirect(url_for('settings.llm.llm_settings_page'))

    @llm_blueprint.route("/llm/clear-summary-cache", methods=['POST'])
    @login_optionally_required
    def llm_clear_summary_cache():
        import glob
        count = 0
        for watch in datastore.data['watching'].values():
            if not watch.data_dir:
                continue
            for f in glob.glob(os.path.join(watch.data_dir, 'change-summary-*.txt')):
                try:
                    os.remove(f)
                    logger.info(f"LLM summary cache removed: {f}")
                    count += 1
                except OSError as e:
                    logger.warning(f"Could not remove LLM summary cache file {f}: {e}")
        logger.info(f"LLM summary cache cleared: {count} file(s) removed")
        flash(gettext("AI summary cache cleared ({} file(s) removed).").format(count), 'notice')
        return redirect(url_for('settings.llm.llm_settings_page'))

    return llm_blueprint
