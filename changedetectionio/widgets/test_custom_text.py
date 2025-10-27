#!/usr/bin/env python3

import sys
import os

from changedetectionio.model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from changedetectionio.widgets import TernaryNoneBooleanField
from wtforms import Form

class TestForm(Form):
    # Default text
    default_field = TernaryNoneBooleanField('Default Field', default=None)
    
    # Custom text with HTML icons
    notification_field = TernaryNoneBooleanField(
        'Notifications',
        default=False,
        yes_text='🔕 Muted', 
        no_text='🔔 Unmuted', 
        none_text='⚙️ System default'
    )
    
    # HTML with styling
    styled_field = TernaryNoneBooleanField(
        'Status',
        default=None,
        yes_text='<strong style="color: green;">✅ Active</strong>',
        no_text='<strong style="color: red;">❌ Inactive</strong>',
        none_text='<em style="color: gray;">🔧 Auto</em>'
    )
    
    # Boolean mode with custom text
    boolean_field = TernaryNoneBooleanField(
        'Boolean Field', 
        default=True,
        boolean_mode=True,
        yes_text="Enabled",
        no_text="Disabled"
    )
    
    # FontAwesome example
    fontawesome_field = TernaryNoneBooleanField(
        'Notifications with FontAwesome',
        default=None,
        yes_text='<i class="fa fa-bell-slash"></i> Muted',
        no_text='<i class="fa fa-bell"></i> Unmuted',
        none_text='<i class="fa fa-cogs"></i> System default'
    )

def test_custom_text():
    """Test custom text functionality"""
    
    form = TestForm()
    
    print("=== Testing TernaryNoneBooleanField Custom Text ===")
    
    # Test default field
    print("\n--- Default Field ---")
    default_field = form.default_field
    default_html = default_field.widget(default_field)
    print(f"Contains 'Yes': {'Yes' in default_html}")
    print(f"Contains 'No': {'No' in default_html}")
    print(f"Contains 'Default': {'Default' in default_html}")
    assert 'Yes' in default_html and 'No' in default_html and 'Default' in default_html
    
    # Test custom text field
    print("\n--- Custom Text Field with Emojis ---")
    notification_field = form.notification_field
    notification_html = notification_field.widget(notification_field)
    print(f"Contains '🔕 Muted': {'🔕 Muted' in notification_html}")
    print(f"Contains '🔔 Unmuted': {'🔔 Unmuted' in notification_html}")
    print(f"Contains '⚙️ System default': {'⚙️ System default' in notification_html}")
    print(f"Does NOT contain 'Yes': {'Yes' not in notification_html}")
    print(f"Does NOT contain 'No': {'No' not in notification_html}")
    assert '🔕 Muted' in notification_html and '🔔 Unmuted' in notification_html
    assert 'Yes' not in notification_html and 'No' not in notification_html
    
    # Test HTML styling
    print("\n--- HTML Styled Field ---")
    styled_field = form.styled_field
    styled_html = styled_field.widget(styled_field)
    print(f"Contains HTML tags: {'<strong' in styled_html}")
    print(f"Contains color styling: {'color: green' in styled_html}")
    print(f"Contains emojis: {'✅' in styled_html and '❌' in styled_html}")
    assert '<strong' in styled_html and 'color: green' in styled_html
    
    # Test boolean mode with custom text
    print("\n--- Boolean Field with Custom Text ---")
    boolean_field = form.boolean_field
    boolean_html = boolean_field.widget(boolean_field)
    print(f"Contains 'Enabled': {'Enabled' in boolean_html}")
    print(f"Contains 'Disabled': {'Disabled' in boolean_html}")
    print(f"Does NOT contain 'System default': {'System default' not in boolean_html}")
    print(f"Does NOT contain 'Default': {'Default' not in boolean_html}")
    assert 'Enabled' in boolean_html and 'Disabled' in boolean_html
    assert USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH not in boolean_html and 'Default' not in boolean_html
    
    # Test FontAwesome field
    print("\n--- FontAwesome Icons Field ---")
    fontawesome_field = form.fontawesome_field
    fontawesome_html = fontawesome_field.widget(fontawesome_field)
    print(f"Contains FontAwesome classes: {'fa fa-bell' in fontawesome_html}")
    print(f"Contains multiple FA icons: {'fa fa-bell-slash' in fontawesome_html and 'fa fa-cogs' in fontawesome_html}")
    assert 'fa fa-bell' in fontawesome_html
    
    print("\n✅ All custom text tests passed!")
    print("\n--- Example Usage ---")
    print("TernaryNoneBooleanField('Status', yes_text='🟢 Online', no_text='🔴 Offline', none_text='🟡 Auto')")
    print("TernaryNoneBooleanField('Notifications', yes_text='<i class=\"fa fa-bell-slash\"></i> Muted', ...)")

def test_data_processing():
    """Test that custom text doesn't affect data processing"""
    print("\n=== Testing Data Processing ===")
    
    form = TestForm()
    field = form.notification_field
    
    # Test form data processing
    field.process_formdata(['true'])
    assert field.data is True, "Custom text should not affect data processing"
    print("✅ True processing works with custom text")
    
    field.process_formdata(['false'])
    assert field.data is False, "Custom text should not affect data processing"
    print("✅ False processing works with custom text")
    
    field.process_formdata(['none'])
    assert field.data is None, "Custom text should not affect data processing"
    print("✅ None processing works with custom text")
    
    print("✅ All data processing tests passed!")

if __name__ == '__main__':
    test_custom_text()
    test_data_processing()