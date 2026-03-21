from wtforms import Form, StringField, TextAreaField, HiddenField, SubmitField, validators, ValidationError
from wtforms.fields import SelectField
from flask_babel import lazy_gettext as _l

from changedetectionio.notification import valid_notification_formats


class ValidateNotificationBodyAndTitleWhenURLisSet:
    """When notification URLs are provided, title and body must also be set."""

    def __call__(self, form, field):
        urls = [u.strip() for u in (field.data or '').splitlines() if u.strip()]
        if urls:
            if not (form.notification_title.data or '').strip():
                raise ValidationError(_l('Notification Title is required when Notification URLs are set'))
            if not (form.notification_body.data or '').strip():
                raise ValidationError(_l('Notification Body is required when Notification URLs are set'))


class NotificationProfileForm(Form):
    name         = StringField(_l('Profile name'), [validators.InputRequired()])
    profile_type = HiddenField(default='apprise')
    save_button  = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})

    # Apprise-type config fields
    notification_urls   = TextAreaField(
        _l('Notification URL list'),
        validators=[validators.Optional(), ValidateNotificationBodyAndTitleWhenURLisSet()],
        render_kw={"rows": 5, "placeholder": "one URL per line\ne.g. mailtos://user:pass@smtp.example.com?to=you@example.com"},
    )
    notification_title  = StringField(_l('Notification title'), validators=[validators.Optional()])
    notification_body   = TextAreaField(_l('Notification body'), validators=[validators.Optional()], render_kw={"rows": 5})
    notification_format = SelectField(
        _l('Notification format'),
        choices=[(k, v) for k, v in valid_notification_formats.items() if k != 'System default'],
    )
