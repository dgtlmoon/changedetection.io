from wtforms import (
    Form,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)
from wtforms.fields.simple import BooleanField
from flask_babel import lazy_gettext as _l

from changedetectionio.processors.restock_diff.forms import processor_settings_form as restock_settings_form
from changedetectionio.llm.ui_strings import LLM_INTENT_TAG_PLACEHOLDER
from changedetectionio.llm.evaluator import DEFAULT_CHANGE_SUMMARY_PROMPT

class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField(_l('Activate for individual watches in this tag/group?'), default=False)

    # Browser config override for this group. Its own dedicated enabler (NOT the coarse
    # legacy `overrides_watch` above) - see resolve_browser_config_override(). When the
    # enabler is on and a config is chosen, member watches use this group's browser config
    # and their own Fetch Method selector is hidden. Choices are set in the tags blueprint.
    browser_config_overrides_watch = BooleanField(_l("Override each watch's browser with"), default=False)
    browser_config = SelectField(_l('Browser config'), validators=[validators.Optional()], choices=[])
    url_match_pattern = StringField(_l('Auto-apply to watches with URLs matching'),
                                    render_kw={"placeholder": _l("e.g. *://example.com/* or github.com/myorg")})
    tag_colour = StringField(_l('Tag colour'), default='')
    llm_intent = TextAreaField('AI Change Intent',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": LLM_INTENT_TAG_PLACEHOLDER})

    llm_change_summary = TextAreaField('AI Change Summary',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "5", "placeholder": DEFAULT_CHANGE_SUMMARY_PROMPT},
                               default='')

class SingleTag(Form):

    name = StringField(_l('Tag name'), [validators.InputRequired()], render_kw={"placeholder": _l("Name")})
    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})
