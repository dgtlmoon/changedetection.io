import re

from wtforms import (
    Form,
    StringField,
    SubmitField,
    ValidationError,
    validators,
)
from wtforms.fields.simple import BooleanField

from changedetectionio.processors.restock_diff.forms import processor_settings_form as restock_settings_form


# Slack webhook URL pattern: https://hooks.slack.com/services/T.../B.../...
SLACK_WEBHOOK_PATTERN = re.compile(
    r'^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+$'
)


def validate_slack_webhook_url(form, field):
    """Validate Slack webhook URL format."""
    if field.data and field.data.strip():
        url = field.data.strip()
        if not SLACK_WEBHOOK_PATTERN.match(url):
            raise ValidationError(
                'Invalid Slack webhook URL format. Expected: '
                'https://hooks.slack.com/services/T<TEAM_ID>/B<BOT_ID>/<TOKEN>'
            )


def validate_hex_color(form, field):
    """Validate hex color format."""
    if field.data and field.data.strip():
        color = field.data.strip()
        if not re.match(r'^#[0-9A-Fa-f]{6}$', color):
            raise ValidationError('Invalid color format. Expected: #RRGGBB (e.g., #3B82F6)')


class group_restock_settings_form(restock_settings_form):
    overrides_watch = BooleanField('Activate for individual watches in this tag/group?', default=False)

    # Slack webhook configuration fields
    slack_webhook_url = StringField(
        'Slack Webhook URL',
        [validators.Optional(), validate_slack_webhook_url],
        render_kw={
            "placeholder": "https://hooks.slack.com/services/T.../B.../...",
            "class": "m-d slack-webhook-url"
        }
    )

    slack_notification_muted = BooleanField(
        'Mute Slack notifications',
        default=False
    )

    tag_color = StringField(
        'Tag Color',
        [validators.Optional(), validate_hex_color],
        render_kw={
            "type": "color",
            "value": "#3B82F6",
            "class": "tag-color-picker"
        }
    )


class SingleTag(Form):

    name = StringField('Tag name', [validators.InputRequired()], render_kw={"placeholder": "Name"})
    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})




