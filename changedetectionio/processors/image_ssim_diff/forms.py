"""
Configuration forms for fast screenshot comparison processor.
"""

from wtforms import SelectField, StringField, validators, ValidationError, IntegerField
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

    processor_config_min_change_percentage = IntegerField(
        'Minimum Change Percentage',
        validators=[
            validators.Optional(),
            validators.NumberRange(min=1, max=100, message='Must be between 0 and 100')
        ],
        render_kw={"placeholder": "Use global default (0.1)"}
    )

    processor_config_pixel_difference_threshold_sensitivity = SelectField(
        'Pixel Difference Sensitivity',
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
        """Render processor-specific form fields.
        @NOTE: prepend processor_config_* to the field name so it will save into its own datadir/uuid/image_ssim_diff.json and be read at process time
        """
        return '''
        {% from '_helpers.html' import render_field %}
        <fieldset>
            <legend>Screenshot Comparison Settings</legend>

            <div class="pure-control-group">
                {{ render_field(form.processor_config_min_change_percentage) }}
                <span class="pure-form-message-inline">
                    <strong>What percentage of pixels must change to trigger a detection?</strong><br>
                    For example, <strong>0.1%</strong> means if 0.1% or more of the pixels change, it counts as a change.<br>
                    Lower values = more sensitive (detect smaller changes).<br>
                    Higher values = less sensitive (only detect larger changes).<br>
                    Leave blank to use global default (0.1%).
                </span>
            </div>

            <div class="pure-control-group">
                {{ render_field(form.processor_config_pixel_difference_threshold_sensitivity) }}
                <span class="pure-form-message-inline">
                    <strong>How different must an individual pixel be to count as "changed"?</strong><br>
                    <strong>Low sensitivity (75)</strong> = Only count pixels that changed significantly (0-255 scale).<br>
                    <strong>High sensitivity (20)</strong> = Count pixels with small changes as different.<br>
                    <strong>Very high (0)</strong> = Any pixel change counts.<br>
                    Select "Use global default" to inherit the system-wide setting.
                </span>
            </div>
        </fieldset>
        '''
