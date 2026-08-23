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
    llm_intent = TextAreaField('AI Change Intent',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": LLM_INTENT_TAG_PLACEHOLDER})

    llm_change_summary = TextAreaField('AI Change Summary',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": DEFAULT_CHANGE_SUMMARY_PROMPT},
                               default='')

    llm_change_summary_mode = RadioField(
        _l('How this prompt combines with the inherited one'),
        choices=[
            (LLM_PROMPT_MODE_REPLACE, _l('Replace the inherited prompt')),
            (LLM_PROMPT_MODE_APPEND,  _l('Append to the inherited prompt')),
        ],
        default=LLM_PROMPT_MODE_REPLACE,
    )

class SingleTag(Form):

    name = StringField(_l('Tag name'), [validators.InputRequired()], render_kw={"placeholder": _l("Name")})
    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})
