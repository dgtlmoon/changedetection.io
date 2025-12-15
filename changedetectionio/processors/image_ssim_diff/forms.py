"""
Configuration forms for SSIM screenshot comparison processor.
"""

from wtforms import SelectField, validators
from changedetectionio.forms import processor_text_json_diff_form


class processor_settings_form(processor_text_json_diff_form):
    """Form for SSIM processor settings."""

    ssim_threshold = SelectField(
        'Screenshot Comparison Sensitivity',
        choices=[
            ('', 'Use global default'),
            ('0.75', 'Low sensitivity (only major changes)'),
            ('0.85', 'Medium sensitivity (moderate changes)'),
            ('0.96', 'High sensitivity (small changes)'),
            ('0.999', 'Very high sensitivity (any change)')
        ],
        validators=[validators.Optional()],
        default=''
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
                {{ render_field(form.ssim_threshold) }}
                <span class="pure-form-message-inline">
                    Controls how sensitive the screenshot comparison is to visual changes.<br>
                    Uses SSIM (Structural Similarity Index) which is robust to antialiasing and minor rendering differences.<br>
                    <strong>Higher sensitivity</strong> = detects smaller changes.<br>
                    Select "Use global default" to inherit the system-wide setting.
                </span>
            </div>
        </fieldset>
        '''
