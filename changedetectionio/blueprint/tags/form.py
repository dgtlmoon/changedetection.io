from flask_babel import lazy_gettext as _l
from wtforms import (
    Form,
    StringField,
    SubmitField,
    validators,
)
from wtforms.fields.simple import BooleanField

from changedetectionio.processors.restock_diff.forms import (
    processor_settings_form as restock_settings_form,
)


class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField('Activate for individual watches in this tag/group?', default=False)
    url_match_pattern = StringField(
        _l('Auto-apply to URLs matching'),
        render_kw={
            "placeholder": _l("e.g. *github.com* or example.com"),
            "class": "m-d"
        }
    )

class SingleTag(Form):

    name = StringField('Tag name', [validators.InputRequired()], render_kw={"placeholder": "Name"})
    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})




