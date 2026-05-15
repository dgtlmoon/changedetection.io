import json
import logging
import os
import re

from flask import Blueprint, jsonify, redirect, url_for, flash
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.auth_decorator import login_optionally_required


class _LiteLLMWarningCapture(logging.Handler):
    """Capture warnings emitted on the 'LiteLLM' stdlib logger during a single call.

    litellm.get_valid_models() catches HTTP/auth errors internally, logs a warning,
    and returns []. Without capturing that warning we can't tell the user *why*
    no models came back (bad key vs. offline vs. genuinely empty model list).
    """
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages = []

    def emit(self, record):
        try:
            self.messages.append(record.getMessage())
        except Exception:
            pass


def _humanize_litellm_error(raw: str) -> str:
    # litellm warnings typically look like:
    #   "Error getting valid models: Failed to get models: { 'error': { 'message': '...' } }"
    # Pull the inner provider message when present; otherwise trim the boilerplate.
    if not raw:
        return raw
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if m:
        try:
            body = json.loads(m.group(0))
            inner = (body.get('error') or {}).get('message') or body.get('message')
            if inner:
                return inner
        except Exception:
            pass
    cleaned = re.sub(r'^Error getting valid models:\s*', '', raw)
    cleaned = re.sub(r'^Failed to get models:\s*', '', cleaned).strip()
    return cleaned[:500]


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

        _PREFIXES = {'gemini': 'gemini/', 'ollama': 'ollama/', 'openrouter': 'openrouter/',
                     'openai_compatible': 'openai/'}
        # vLLM / LM Studio / llama.cpp speak OpenAI's wire format — route through litellm's
        # 'openai' provider but keep the UI-level name distinct from cloud OpenAI.
        _LITELLM_PROVIDER = {'openai_compatible': 'openai'}
        prefix = _PREFIXES.get(provider, '')
        litellm_provider = _LITELLM_PROVIDER.get(provider, provider)

        try:
            import litellm
            logger.debug(f"LLM model list: calling litellm.get_valid_models provider={provider!r} (litellm={litellm_provider!r}) api_base={api_base!r}")

            capture = _LiteLLMWarningCapture()
            litellm_logger = logging.getLogger('LiteLLM')
            litellm_logger.addHandler(capture)
            try:
                raw = litellm.get_valid_models(
                    check_provider_endpoint=True,
                    custom_llm_provider=litellm_provider,
                    api_key=api_key or None,
                    api_base=api_base or None,
                ) or []
            finally:
                litellm_logger.removeHandler(capture)

            models = sorted({(m if m.startswith(prefix) else prefix + m) for m in raw})

            if not models and capture.messages:
                err = _humanize_litellm_error(capture.messages[-1])
                logger.debug(f"LLM model list: 0 models, surfacing captured litellm warning: {err!r}")
                return jsonify({'models': [], 'error': err}), 400

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
            # Reuse the same multiplier path the production calls use, so cloud providers
            # stay on a small base cap (matching upstream's pre-existing behavior) and only
            # 'openai_compatible' endpoints opt into the reasoning-friendly headroom.
            from changedetectionio.llm.evaluator import apply_local_token_multiplier
            text, total_tokens, input_tokens, output_tokens = completion(
                model=model,
                messages=[{'role': 'user', 'content':
                    'Respond with just the word: ready'}],
                api_key=llm_cfg.get('api_key') or None,
                api_base=api_base or None,
                timeout=30,
                max_tokens=apply_local_token_multiplier(200, llm_cfg),
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
