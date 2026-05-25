from flask import Blueprint, render_template

from changedetectionio import forms
from changedetectionio.auth_decorator import login_optionally_required
from changedetectionio.store import ChangeDetectionStore


def construct_blueprint(datastore: ChangeDetectionStore):
    add_watch_ui_blueprint = Blueprint('add_watch_ui', __name__, template_folder="templates")

    @add_watch_ui_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def index():
        from changedetectionio.llm.evaluator import get_llm_config as _get_llm_config
        from changedetectionio.llm.ui_strings import LLM_INTENT_WATCH_PLACEHOLDER

        form = forms.quickWatchForm(None)
        llm_configured = bool(_get_llm_config(datastore))

        return render_template(
            "add-watch-ui.html",
            form=form,
            llm_configured=llm_configured,
            llm_intent_watch_placeholder=LLM_INTENT_WATCH_PLACEHOLDER,
        )

    return add_watch_ui_blueprint
