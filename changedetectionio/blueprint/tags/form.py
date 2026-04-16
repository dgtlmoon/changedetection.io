from wtforms import (
    Form,
    StringField,
    SubmitField,
    TextAreaField,
    validators,
)
from wtforms.fields.simple import BooleanField

from changedetectionio.processors.restock_diff.forms import processor_settings_form as restock_settings_form

class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField('Activate for individual watches in this tag/group?', default=False)
    url_match_pattern = StringField('Auto-apply to watches with URLs matching',
                                    render_kw={"placeholder": "e.g. *://example.com/* or github.com/myorg"})
    tag_colour = StringField('Tag colour', default='')
    llm_intent = TextAreaField('AI Intent',
                               validators=[validators.Optional(), validators.Length(max=2000)],
                               render_kw={"rows": "3",
                                          "placeholder": "e.g. Flag price changes or new product launches across all watches in this group"})

class SingleTag(Form):

    name = StringField('Tag name', [validators.InputRequired()], render_kw={"placeholder": "Name"})
    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})
