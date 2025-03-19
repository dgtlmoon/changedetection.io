"""
Example plugin to demonstrate how to create a new processor plugin
"""
from .pluggy_interface import hookimpl
from .text_json_diff.processor import perform_site_check as text_json_diff_perform_site_check
from changedetectionio import forms

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
    def perform_site_check(self, datastore, watch_uuid):
        watch = datastore.data['watching'].get(watch_uuid)
        if watch and watch.get('processor') == 'example_processor':
            # This processor is just a wrapper around text_json_diff for demonstration
            return text_json_diff_perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
        return None

    @hookimpl
    def get_form_class(self, processor_name):
        if processor_name == 'example_processor':
            # Use the default form for this example
            return forms.processor_text_json_diff_form
        return None

    @hookimpl
    def get_watch_model_class(self, processor_name):
        if processor_name == 'example_processor':
            # Use the default Watch model for this example
            from changedetectionio.model import Watch
            return Watch.model
        return None

# This function would be called by the setup.py entry_points
def register_plugin(plugin_manager):
    plugin_manager.register(ExampleProcessorPlugin())