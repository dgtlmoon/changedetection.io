"""
Configuration forms for fast screenshot comparison processor.
"""

from wtforms import SelectField, StringField, validators, ValidationError, IntegerField
from flask_babel import lazy_gettext as _l
from changedetectionio.forms import processor_text_json_diff_form
import re

from changedetectionio.processors.image_ssim_diff import SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS


def validate_bounding_box(form, field):
    """Validate bounding box format: x,y,width,height with integers."""
    if not field.data:
        return  # Optional field

    if len(field.data) > 100:
        raise ValidationError(_l('Bounding box value is too long'))

    # Should be comma-separated integers
    if not re.match(r'^\d+,\d+,\d+,\d+$', field.data):
        raise ValidationError(_l('Bounding box must be in format: x,y,width,height (integers only)'))

    # Validate values are reasonable (not negative, not ridiculously large)
    parts = [int(p) for p in field.data.split(',')]
    for part in parts:
        if part < 0:
            raise ValidationError(_l('Bounding box values must be non-negative'))
        if part > 10000:  # Reasonable max screen dimension
            raise ValidationError(_l('Bounding box values are too large'))


def validate_selection_mode(form, field):
    """Validate selection mode value."""
    if not field.data:
        return  # Optional field

    if field.data not in ['element', 'draw']:
        raise ValidationError(_l('Selection mode must be either "element" or "draw"'))


class processor_settings_form(processor_text_json_diff_form):
    """Form for fast image comparison processor settings."""

    processor_config_min_change_percentage = IntegerField(
        _l('Minimum Change Percentage'),
        validators=[
            validators.Optional(),
            validators.NumberRange(min=1, max=100, message=_l('Must be between 0 and 100'))
        ],
        render_kw={"placeholder": "Use global default (0.1)"}
    )

    processor_config_pixel_difference_threshold_sensitivity = SelectField(
        _l('Pixel Difference Sensitivity'),
        choices=[
                    ('', _l('Use global default'))
                ] + SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS,
        validators=[validators.Optional()],
        default=''
    )

    # Processor-specific config fields (stored in separate JSON file)
    processor_config_bounding_box = StringField(
        _l('Bounding Box'),
        validators=[
            validators.Optional(),
            validators.Length(max=100, message=_l('Bounding box value is too long')),
            validate_bounding_box
        ],
        render_kw={"style": "display: none;", "id": "bounding_box"}
    )

    processor_config_selection_mode = StringField(
        _l('Selection Mode'),
        validators=[
            validators.Optional(),
            validators.Length(max=20, message=_l('Selection mode value is too long')),
            validate_selection_mode
        ],
        render_kw={"style": "display: none;", "id": "selection_mode"}
    )

    def extra_tab_content(self):
        """Tab label for processor-specific settings."""
        return _l('Screenshot Comparison')

    def extra_form_template(self):
        """Processor-specific form fields, rendered with Flask's render_template() so they are translatable.
        @NOTE: prepend processor_config_* to the field name so it will save into its own datadir/uuid/image_ssim_diff.json and be read at process time
        """
        return 'image_ssim_diff/edit-extras.html'
