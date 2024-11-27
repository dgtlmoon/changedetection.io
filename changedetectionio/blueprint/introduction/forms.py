from wtforms import (
    Form,
    StringField,
    SubmitField,
    validators,
)

from changedetectionio.forms import validateTimeZoneName


class IntroductionSettings(Form):

    default_timezone = StringField("Timezone to run in",
                                  render_kw={"list": "timezones", 'required': 'required'},
                                  validators=[validateTimeZoneName()]
                                  )

    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})




