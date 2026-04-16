from wtforms import (
    Form,
    StringField,
    SubmitField,
    validators,
)
from wtforms.fields.simple import BooleanField
from flask_babel import lazy_gettext as _l

from changedetectionio.processors.restock_diff.forms import processor_settings_form as restock_settings_form

class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField(_l('Activate for individual watches in this tag/group?'), default=False)
    url_match_pattern = StringField(_l('Auto-apply to watches with URLs matching'),
                                    render_kw={"placeholder": _l("e.g. *://example.com/* or github.com/myorg")})
    tag_colour = StringField(_l('Tag colour'), default='')

class SingleTag(Form):

    name = StringField(_l('Tag name'), [validators.InputRequired()], render_kw={"placeholder": _l("Name")})
    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})
