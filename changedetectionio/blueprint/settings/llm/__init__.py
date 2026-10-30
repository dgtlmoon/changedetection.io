import os

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def save_llm_form(datastore, llm_form_data):
    """Merge the submitted AI / LLM form over the stored settings (settings.application.llm)."""
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
    """What llm-settings.html needs, besides the form."""
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


def construct_llm_blueprint(datastore: ChangeDetectionStore):
    llm_blueprint = Blueprint('llm', __name__, template_folder="templates")

    # Its link in the left sidebar, only when this page exists ('builtin_' plugins aren't listed as active plugins)
    from changedetectionio.pluggy_interface import plugin_manager
    from changedetectionio.blueprint.settings.llm import sidebar
    if not plugin_manager.is_registered(sidebar):
        plugin_manager.register(sidebar, 'builtin_llm_sidebar')

    @llm_blueprint.route("", methods=['GET', 'POST'], strict_slashes=False)
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

        return render_template("llm-settings.html", form=form, **llm_template_context(datastore))

    @llm_blueprint.route("/models", methods=['GET'])
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
            elif api_base:
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

    @llm_blueprint.route("/test", methods=['POST'])
    @login_optionally_required
    def llm_test():
        from flask import request
        from changedetectionio.llm.client import completion_isolated
        from changedetectionio.validate_url import is_llm_api_base_safe

        # Pull stored config as the fallback, then override with anything the
        # form-driven JS sent as query params. Lets users test config changes
        # without first hitting Save (matching how /settings/llm/models works).
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
            logger.warning("LLM connection test refused: api_base differs from saved config but no api_key supplied")
            return jsonify({'ok': False, 'error': gettext(
                "api_key is required when api_base differs from the saved configuration. "
                "Refusing to send the stored API key to a different endpoint."
            )}), 400

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
    @llm_blueprint.route("/clear", methods=['POST'])
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

    @llm_blueprint.route("/clear-summary-cache", methods=['POST'])
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
