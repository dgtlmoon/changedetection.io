import pytest
from time import sleep
from copy import deepcopy
from ..processors import pluggy_interface
from ..processors.pluggy_interface import PLUGIN_NAMESPACE
from ..processors import get_all_plugins_info, available_processors, get_form_class_for_processor
from ..processors.text_json_diff.processor import perform_site_check

def test_plugin_interfaces():
    """Test that the plugin interface is functioning correctly"""
    # The plugin manager should be already set up
    assert pluggy_interface.plugin_manager is not None
    assert pluggy_interface.plugin_manager.get_namespace() == PLUGIN_NAMESPACE
    
    # Check that we can get plugins
    plugins = pluggy_interface.plugin_manager.get_plugins()
    assert len(plugins) >= 3  # Should have at least the 3 built-in plugins
    
    # Check that the TextJsonDiffPlugin is registered
    for plugin in plugins:
        if hasattr(plugin, "get_processor_name") and plugin.get_processor_name() == "text_json_diff":
            assert plugin.get_processor_description() is not None
            assert plugin.get_processor_version() is not None
            break
    else:
        assert False, "TextJsonDiffPlugin not found"
    
    # Check plugin info collection
    plugin_info = get_all_plugins_info()
    assert len(plugin_info) >= 3
    
    # Check processor list generation
    processor_list = available_processors()
    assert len(processor_list) >= 3
    
    # Ensure each processor has a name and description
    for name, description in processor_list:
        assert name is not None
        assert description is not None
        
def test_plugin_form_and_model_handling():
    """Test that plugin form and model handling works"""
    # Test getting the form class for text_json_diff
    form_class = get_form_class_for_processor("text_json_diff")
    assert form_class is not None
    
    # Test getting the form class for a non-existent processor
    form_class = get_form_class_for_processor("non_existent_processor")
    assert form_class is not None  # Should return the default text_json_diff form
    
def test_plugin_enabled_filters(client, live_server):
    """Test that enabled plugins filter works"""
    # Create a fake datastore with plugin settings and tracking for writes
    datastore = type('MockDatastore', (object,), {
        'data': {
            'settings': {
                'application': {
                    'enabled_plugins': {
                        'text_json_diff': True,
                        'restock_diff': False,
                        'example_processor': True
                    }
                }
            }
        },
        'needs_write': False
    })
    
    # Get processors filtered by enabled status
    processor_list = available_processors(datastore)
    
    # Should have text_json_diff and example_processor, but not restock_diff
    processor_names = [name for name, desc in processor_list]
    assert 'text_json_diff' in processor_names
    assert 'example_processor' in processor_names
    assert 'restock_diff' not in processor_names
    
    # Test with empty enabled_plugins (should auto-populate with defaults)
    datastore.data['settings']['application']['enabled_plugins'] = {}
    processor_list = available_processors(datastore)
    
    # Check that it detected and auto-populated missing plugins
    assert len(datastore.data['settings']['application']['enabled_plugins']) >= 3
    assert datastore.needs_write == True
    
    # Built-in processors should be enabled by default
    assert datastore.data['settings']['application']['enabled_plugins']['text_json_diff'] == True
    assert datastore.data['settings']['application']['enabled_plugins']['restock_diff'] == True
    
    # Third-party processors should be disabled by default
    assert datastore.data['settings']['application']['enabled_plugins']['example_processor'] == False
    
    # Only enabled processors should be in the list
    processor_names = [name for name, desc in processor_list]
    assert 'text_json_diff' in processor_names
    assert 'restock_diff' in processor_names 
    assert 'example_processor' not in processor_names
    
def test_plugin_example_implementation():
    """Test the example plugin implementation"""
    from ..processors.example_processor_plugin import ExampleProcessorPlugin
    
    plugin = ExampleProcessorPlugin()
    assert plugin.get_processor_name() == "example_processor"
    assert "Example Processor Plugin" in plugin.get_processor_description()
    assert plugin.get_processor_version() is not None
    
    # Test the form class
    form_class = plugin.get_form_class(processor_name="example_processor")
    assert form_class is not None
    assert hasattr(form_class, "example_settings")
    
    # Test the model class
    model_class = plugin.get_watch_model_class(processor_name="example_processor")
    assert model_class is not None
    
    # Create an instance of the model and check its methods
    model_instance = model_class()
    assert hasattr(model_instance, "get_example_threshold")
    assert hasattr(model_instance, "is_example_mode_enabled")