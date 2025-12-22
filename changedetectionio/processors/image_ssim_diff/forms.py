"""
Configuration forms for fast screenshot comparison processor.
"""

from wtforms import SelectField, StringField, validators, ValidationError
from changedetectionio.forms import processor_text_json_diff_form
import re

from changedetectionio.processors.image_ssim_diff import SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS


def validate_bounding_box(form, field):
    """Validate bounding box format: x,y,width,height with integers."""
    if not field.data:
        return  # Optional field

    if len(field.data) > 100:
        raise ValidationError('Bounding box value is too long')

    # Should be comma-separated integers
    if not re.match(r'^\d+,\d+,\d+,\d+$', field.data):
        raise ValidationError('Bounding box must be in format: x,y,width,height (integers only)')

    # Validate values are reasonable (not negative, not ridiculously large)
    parts = [int(p) for p in field.data.split(',')]
    for part in parts:
        if part < 0:
            raise ValidationError('Bounding box values must be non-negative')
        if part > 10000:  # Reasonable max screen dimension
            raise ValidationError('Bounding box values are too large')


def validate_selection_mode(form, field):
    """Validate selection mode value."""
    if not field.data:
        return  # Optional field

    if field.data not in ['element', 'draw']:
        raise ValidationError('Selection mode must be either "element" or "draw"')


class processor_settings_form(processor_text_json_diff_form):
    """Form for fast image comparison processor settings."""

    comparison_threshold = SelectField(
        'Screenshot Comparison Sensitivity',
        choices=[
                    ('', 'Use global default')
                ] + SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS,
        validators=[validators.Optional()],
        default=''
    )

    # Processor-specific config fields (stored in separate JSON file)
    processor_config_bounding_box = StringField(
        'Bounding Box',
        validators=[
            validators.Optional(),
            validators.Length(max=100, message='Bounding box value is too long'),
            validate_bounding_box
        ],
        render_kw={"style": "display: none;", "id": "bounding_box"}
    )

    processor_config_selection_mode = StringField(
        'Selection Mode',
        validators=[
            validators.Optional(),
            validators.Length(max=20, message='Selection mode value is too long'),
            validate_selection_mode
        ],
        render_kw={"style": "display: none;", "id": "selection_mode"}
    )

    def extra_tab_content(self):
        """Tab label for processor-specific settings."""
        return 'Screenshot Comparison'

    def extra_form_content(self):
        """Render processor-specific form fields."""
        return '''
        {% from '_helpers.html' import render_field %}
        <fieldset>
            <legend>Screenshot Comparison Settings</legend>
            <div class="pure-control-group">
                {{ render_field(form.comparison_threshold) }}
                <span class="pure-form-message-inline">
                    Controls how sensitive the screenshot comparison is to visual changes.<br>
                    <strong>Higher sensitivity</strong> = detects smaller changes but may trigger on minor rendering differences.<br>
                    Select "Use global default" to inherit the system-wide setting.
                </span>
            </div>
        </fieldset>
        '''
