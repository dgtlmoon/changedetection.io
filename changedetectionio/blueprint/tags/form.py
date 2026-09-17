from wtforms import (
    Form,
    RadioField,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)
from wtforms.fields.simple import BooleanField
from flask_babel import lazy_gettext as _l

from changedetectionio.blueprint.tags.colour import CSS_HEX_COLOUR_REGEX
from changedetectionio.widgets.ternary_boolean import TernaryNoneBooleanField
from changedetectionio.processors.restock_diff.forms import processor_settings_form as restock_settings_form
from changedetectionio.llm.ui_strings import LLM_INTENT_TAG_PLACEHOLDER
from changedetectionio.llm.evaluator import (
    DEFAULT_CHANGE_SUMMARY_PROMPT,
    LLM_PROMPT_MODE_APPEND,
    LLM_PROMPT_MODE_REPLACE,
)

class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField(_l('Activate for individual watches in this tag/group?'), default=False)
    url_match_pattern = StringField(_l('Auto-apply to watches with URLs matching'),
                                    render_kw={"placeholder": _l("e.g. *://example.com/* or github.com/myorg")})
    # Rendered into a <style> block, so only a plain hex colour is accepted, see colour.py
    tag_colour = StringField(_l('Tag colour'),
                             default='',
                             validators=[validators.Optional(),
                                         validators.Regexp(CSS_HEX_COLOUR_REGEX,
                                                           message=_l('Must be a hex colour, for example #4f8ef7'))])
    # The group's one and only AI control. Same key as the per-watch switch (see forms.py) but
    # ternary, because a group has a third useful answer: "no opinion, leave it to each watch"
    # (the default). See tag_llm_decision() for the semantics of each state — #4204.
    # @NOTE! In the near future this stops being a ternary bool and becomes a *profile*
    #        selector — pick one of the configured LLM profiles, or 'off', or inherit. The
    #        field name is already the future one; only the widget and the True/False/None
    #        value space need to change, so keep reads going through tag_llm_decision().
    llm_backend_profile = TernaryNoneBooleanField(
        _l('AI for watches in this group'),
        default=None,
        yes_text=_l('On, use the settings below'),
        no_text=_l('Off for every watch'),
        none_text=_l('Leave it to each watch'),
    )

    llm_intent = TextAreaField('AI Change Intent - Notify me when..',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": LLM_INTENT_TAG_PLACEHOLDER})

    llm_change_summary = TextAreaField('AI Change Summary',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": DEFAULT_CHANGE_SUMMARY_PROMPT},
                               default='')

    llm_change_summary_mode = RadioField(
        _l('Change Summary prompt - Append or Replace the default?'),
        choices=[
            (LLM_PROMPT_MODE_REPLACE, _l('Replace the inherited prompt')),
            (LLM_PROMPT_MODE_APPEND,  _l('Append to the inherited prompt')),
        ],
        default=LLM_PROMPT_MODE_REPLACE,
    )

class SingleTag(Form):

    name = StringField(_l('Tag name'), [validators.InputRequired()], render_kw={"placeholder": _l("Name")})
    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})
