"""
Configuration forms for fast screenshot comparison processor.
"""

from wtforms import SelectField, validators
from changedetectionio.forms import processor_text_json_diff_form


class processor_settings_form(processor_text_json_diff_form):
    """Form for fast image comparison processor settings."""

    comparison_method = SelectField(
        'Comparison Method',
        choices=[
            ('', 'Use global default'),
            ('opencv', 'OpenCV (Fastest, simple pixel difference)'),
            ('pixelmatch', 'Pixelmatch (Fast, anti-aliasing aware)')
        ],
        validators=[validators.Optional()],
        default=''
    )

    comparison_threshold = SelectField(
        'Screenshot Comparison Sensitivity',
        choices=[
            ('', 'Use global default'),
            ('10', 'Very low sensitivity (only major changes)'),
            ('20', 'Low sensitivity (significant changes)'),
            ('30', 'Medium sensitivity (moderate changes)'),
            ('50', 'High sensitivity (small changes)'),
            ('75', 'Very high sensitivity (any visible change)')
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
                {{ render_field(form.comparison_method) }}
                <span class="pure-form-message-inline">
                    <strong>OpenCV:</strong> 50-100x faster, uses simple pixel difference with Gaussian blur for noise reduction.<br>
                    <strong>Pixelmatch:</strong> 10-20x faster, specifically designed for screenshots with anti-aliasing detection.<br>
                    Both methods are dramatically faster than the old SSIM algorithm.
                </span>
            </div>
            <div class="pure-control-group">
                {{ render_field(form.comparison_threshold) }}
                <span class="pure-form-message-inline">
                    Controls how sensitive the screenshot comparison is to visual changes.<br>
                    <strong>OpenCV:</strong> Threshold for pixel difference (0-255). Lower = more sensitive.<br>
                    <strong>Pixelmatch:</strong> Threshold for color distance (0-1 range, scaled from 0-100).<br>
                    <strong>Higher sensitivity</strong> = detects smaller changes but may trigger on minor rendering differences.<br>
                    Select "Use global default" to inherit the system-wide setting.
                </span>
            </div>
        </fieldset>
        '''
