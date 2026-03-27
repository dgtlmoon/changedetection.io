from wtforms import Form, StringField, TextAreaField, HiddenField, SubmitField, validators
from wtforms.fields import SelectField
from flask_babel import lazy_gettext as _l

from changedetectionio.notification import valid_notification_formats


class NotificationProfileForm(Form):
    name         = StringField(_l('Profile name'), [validators.InputRequired()])
    profile_type = HiddenField(default='apprise')
    save_button  = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})

    # Apprise-type config fields
    notification_urls   = TextAreaField(
        _l('Notification URL list'),
        validators=[validators.Optional()],
        render_kw={"rows": 5, "placeholder": "one URL per line\ne.g. mailtos://user:pass@smtp.example.com?to=you@example.com"},
    )
    notification_title  = StringField(_l('Notification title'), validators=[validators.Optional()])
    notification_body   = TextAreaField(_l('Notification body'), validators=[validators.Optional()], render_kw={"rows": 5})
    notification_format = SelectField(
        _l('Notification format'),
        choices=[(k, v) for k, v in valid_notification_formats.items() if k != 'System default'],
    )


class AppriseDefaultsForm(Form):
    """System-wide defaults for the Apprise notification type."""
    notification_title  = StringField(
        _l('Default notification title'),
        validators=[validators.Optional()],
        render_kw={"placeholder": "ChangeDetection.io Notification - {{watch_url}}"},
    )
    notification_body   = TextAreaField(
        _l('Default notification body'),
        validators=[validators.Optional()],
        render_kw={"rows": 6, "placeholder": "{{watch_url}} had a change.\n---\n{{diff}}\n---\n"},
    )
    notification_format = SelectField(
        _l('Default notification format'),
        choices=[(k, v) for k, v in valid_notification_formats.items() if k != 'System default'],
    )
    save_button = SubmitField(_l('Save defaults'), render_kw={"class": "pure-button pure-button-primary"})
