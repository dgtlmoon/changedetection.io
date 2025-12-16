"""
Configuration forms for fast screenshot comparison processor.
"""

from wtforms import SelectField, validators
from changedetectionio.forms import processor_text_json_diff_form


class processor_settings_form(processor_text_json_diff_form):
    """Form for fast image comparison processor settings."""

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
                {{ render_field(form.comparison_threshold) }}
                <span class="pure-form-message-inline">
                    Controls how sensitive the screenshot comparison is to visual changes.<br>
                    <strong>Higher sensitivity</strong> = detects smaller changes but may trigger on minor rendering differences.<br>
                    Select "Use global default" to inherit the system-wide setting.
                </span>
            </div>
        </fieldset>
        '''
