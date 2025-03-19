"""
Example plugin to demonstrate how to create a new processor plugin
"""
from .pluggy_interface import hookimpl
import importlib

class ExampleProcessorPlugin:
    """
    Example processor plugin that extends the text_json_diff processor
    """
    
    @hookimpl
    def get_processor_name(self):
        return "example_processor"

    @hookimpl
    def get_processor_description(self):
        return "Example Processor Plugin - For demonstration purposes"
        
    @hookimpl
    def get_processor_version(self):
        return "0.1.0-beta"

    @hookimpl
    def perform_site_check(self, datastore, watch_uuid):
        watch = datastore.data['watching'].get(watch_uuid)
        if watch and watch.get('processor') == 'example_processor':
            # Log that we're using our special example processor
            from loguru import logger
            
            # Check if the example mode is enabled
            if watch.is_example_mode_enabled():
                # Get the threshold value for our plugin
                threshold = watch.get_example_threshold()
                logger.info(f"Example processor using mode: {watch.get('example_settings', {}).get('mode')} with threshold: {threshold}")
                
                # Check if advanced features are enabled
                advanced_features = watch.get('example_settings', {}).get('example_toggle', False)
                if advanced_features:
                    logger.info("Example processor advanced features are enabled")
            else:
                logger.info("Example processor is in OFF mode, using standard processing")
            
            # Import here to avoid circular imports
            from changedetectionio.processors.text_json_diff.processor import perform_site_check
            return perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
        return None

    @hookimpl
    def get_form_class(self, processor_name):
        if processor_name == 'example_processor':
            # Import here to avoid circular imports
            from changedetectionio import forms
            from wtforms import StringField, BooleanField, TextAreaField, RadioField, FloatField
            from wtforms.validators import Optional, NumberRange
            from wtforms.fields.form import FormField
            from wtforms.form import Form
            
            # Create a settings form for the example plugin
            class ExampleSettingsForm(Form):
                mode = RadioField(label='Example Mode', choices=[
                    ('mode_a', "Mode A - Default behavior"),
                    ('mode_b', "Mode B - Alternative behavior"),
                    ('off', "Off - Disable example functionality"),
                ], default="mode_a")
                
                threshold = FloatField('Threshold value', [
                    Optional(), 
                    NumberRange(min=0, max=100, message="Should be between 0 and 100")
                ], render_kw={"placeholder": "0", "size": "5"})
                
                example_toggle = BooleanField('Enable advanced features', default=False)
                example_notes = TextAreaField('Notes', validators=[Optional()])
            
            # Create the main form by extending the base form
            class ExampleProcessorForm(forms.processor_text_json_diff_form):
                example_settings = FormField(ExampleSettingsForm)
                
                def extra_tab_content(self):
                    return 'Example Plugin'
                
                def extra_form_content(self):
                    output = ""
                    
                    # Show warning if tag overrides settings (similar to restock plugin)
                    if getattr(self, 'watch', None) and getattr(self, 'datastore'):
                        for tag_uuid in self.watch.get('tags'):
                            tag = self.datastore.data['settings']['application']['tags'].get(tag_uuid, {})
                            if tag.get('overrides_watch'):
                                output = f"""<p><strong>Note! A Group tag overrides the example plugin settings here.</strong></p><style>#example-fieldset-group {{ opacity: 0.6; }}</style>"""
                    
                    output += """
                    {% from '_helpers.html' import render_field, render_checkbox_field, render_button %}
                    <script>        
                        $(document).ready(function () {
                            toggleOpacity('#example_settings-example_toggle', '.example-advanced-settings', true);
                        });
                    </script>
                    
                    <fieldset id="example-fieldset-group">
                        <div class="pure-control-group">
                            <fieldset class="pure-group inline-radio">
                                {{ render_field(form.example_settings.mode) }}
                            </fieldset>
                            <fieldset class="pure-group">
                                {{ render_checkbox_field(form.example_settings.example_toggle) }}
                                <span class="pure-form-message-inline">Enable advanced example features</span>
                            </fieldset>
                            <fieldset class="pure-group example-advanced-settings">
                                {{ render_field(form.example_settings.threshold) }}
                                <span class="pure-form-message-inline">Set the threshold percentage for this example plugin</span>
                                <span class="pure-form-message-inline">For example, 5% means the plugin will only activate when changes exceed 5% of the content</span>
                            </fieldset>
                            <fieldset class="pure-group example-advanced-settings">
                                {{ render_field(form.example_settings.example_notes, rows=3, placeholder="Add any notes here...") }}
                                <span class="pure-form-message-inline">Additional notes for this watch</span>
                            </fieldset>
                        </div>
                    </fieldset>
                    """
                    return output
            
            return ExampleProcessorForm
        return None

    @hookimpl
    def get_watch_model_class(self, processor_name):
        if processor_name == 'example_processor':
            # Import here to avoid circular imports
            from changedetectionio.model import Watch
            
            # Create a custom Watch model class for the example plugin
            class ExampleWatchModel(Watch.model):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    
                    # Initialize example plugin settings if not present
                    if not self.get('example_settings'):
                        self['example_settings'] = {
                            'mode': 'mode_a',
                            'threshold': 0,
                            'example_toggle': False,
                            'example_notes': ''
                        }
                
                # Add any custom methods for the example plugin
                def get_example_threshold(self):
                    """Get the threshold value or return the default"""
                    settings = self.get('example_settings', {})
                    return settings.get('threshold', 0)
                
                def is_example_mode_enabled(self):
                    """Check if the example plugin is enabled"""
                    settings = self.get('example_settings', {})
                    return settings.get('mode') != 'off'
            
            return ExampleWatchModel
        return None

# This function would be called by the setup.py entry_points
def register_plugin(plugin_manager):
    plugin_manager.register(ExampleProcessorPlugin())