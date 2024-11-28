from wtforms import (
    Form,
    StringField,
    SubmitField,
)

from changedetectionio.forms import validateTimeZoneName


class IntroductionSettings(Form):

    default_timezone = StringField("Default timezone",
                                  render_kw={"list": "timezones", 'required': 'required'},
                                  validators=[validateTimeZoneName()]
                                  )

    save_button = SubmitField('Save & Continue', render_kw={"class": "pure-button pure-button-primary"})




