import os

from flask import Blueprint, jsonify, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


def construct_llm_blueprint(datastore: ChangeDetectionStore):
    llm_blueprint = Blueprint('llm', __name__)

    @llm_blueprint.route("/models", methods=['GET'])
    @login_optionally_required
    def llm_get_models():
        from flask import request
        provider = request.args.get('provider', '').strip()
        api_key  = request.args.get('api_key',  '').strip()
        api_base = request.args.get('api_base', '').strip()

        logger.debug(f"LLM model list requested for provider={provider!r} api_base={api_base!r}")

        if not provider:
            logger.debug("LLM model list: no provider specified, returning 400")
            return jsonify({'models': [], 'error': 'No provider specified'}), 400

        # Fall back to the stored key if the user hasn't typed one yet
        if not api_key:
            api_key = (datastore.data['settings']['application'].get('llm') or {}).get('api_key', '')
            logger.debug("LLM model list: no api_key in request, using stored key")

        _PREFIXES = {'gemini': 'gemini/', 'ollama': 'ollama/', 'openrouter': 'openrouter/'}
        prefix = _PREFIXES.get(provider, '')

        try:
            import litellm
            logger.debug(f"LLM model list: calling litellm.get_valid_models provider={provider!r} api_base={api_base!r}")
            raw = litellm.get_valid_models(
                check_provider_endpoint=True,
                custom_llm_provider=provider,
                api_key=api_key or None,
                api_base=api_base or None,
            ) or []
            models = sorted({(m if m.startswith(prefix) else prefix + m) for m in raw})
            logger.debug(f"LLM model list: got {len(models)} models for provider={provider!r}")
            return jsonify({'models': models, 'error': None})
        except Exception as e:
            logger.error(f"LLM model list failed for provider={provider!r}: {e}")
            logger.exception("LLM model list full traceback:")
            return jsonify({'models': [], 'error': str(e)}), 400

    @llm_blueprint.route("/test", methods=['GET'])
    @login_optionally_required
    def llm_test():
        from changedetectionio.llm.client import completion

        llm_cfg = datastore.data['settings']['application'].get('llm') or {}
        model    = llm_cfg.get('model', '').strip()
        api_base = llm_cfg.get('api_base', '') or ''

        logger.debug(f"LLM connection test requested: model={model!r} api_base={api_base!r}")

        if not model:
            logger.error("LLM connection test failed: no model configured in datastore")
            return jsonify({'ok': False, 'error': 'No model configured.'}), 400

        try:
            logger.debug(f"LLM connection test: sending test prompt to model={model!r}")
            text, total_tokens, input_tokens, output_tokens = completion(
                model=model,
                messages=[{'role': 'user', 'content':
                    'Reply with exactly five words confirming you are ready.'}],
                api_key=llm_cfg.get('api_key') or None,
                api_base=api_base or None,
                timeout=20,
                max_tokens=200,
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

    @llm_blueprint.route("/clear", methods=['GET'])
    @login_optionally_required
    def llm_clear():
        logger.debug("LLM configuration cleared by user")
        datastore.data['settings']['application'].pop('llm', None)
        datastore.commit()
        flash(gettext("AI / LLM configuration removed."), 'notice')
        return redirect(url_for('settings.settings_page') + '#ai')

    @llm_blueprint.route("/clear-summary-cache", methods=['GET'])
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
        return redirect(url_for('settings.settings_page') + '#ai')

    return llm_blueprint
