from wtforms import Field
from markupsafe import Markup
from flask_babel import lazy_gettext as _l

class TernaryNoneBooleanWidget:
    """
    A widget that renders a horizontal radio button group with either two options (Yes/No)
    or three options (Yes/No/Default), depending on the field's boolean_mode setting.
    """
    def __call__(self, field, **kwargs):
        html = ['<div class="ternary-radio-group pure-form">']
        
        field_id = kwargs.pop('id', field.id)
        boolean_mode = getattr(field, 'boolean_mode', False)
        
        # Get custom text or use defaults
        yes_text = getattr(field, 'yes_text', _l('Yes'))
        no_text = getattr(field, 'no_text', _l('No'))
        none_text = getattr(field, 'none_text', _l('Main settings'))
        
        # True option
        checked_true = ' checked' if field.data is True else ''
        html.append(f'''
            <label class="ternary-radio-option">
                <input type="radio" name="{field.name}" value="true" id="{field_id}_true"{checked_true} class="pure-radio">
                <span class="ternary-radio-label pure-button-primary">{yes_text}</span>
            </label>
        ''')
        
        # False option  
        checked_false = ' checked' if field.data is False else ''
        html.append(f'''
            <label class="ternary-radio-option">
                <input type="radio" name="{field.name}" value="false" id="{field_id}_false"{checked_false} class="pure-radio">
                <span class="ternary-radio-label">{no_text}</span>
            </label>
        ''')
        
        # None option (only show if not in boolean mode)
        if not boolean_mode:
            checked_none = ' checked' if field.data is None else ''
            html.append(f'''
                <label class="ternary-radio-option">
                    <input type="radio" name="{field.name}" value="none" id="{field_id}_none"{checked_none} class="pure-radio">
                    <span class="ternary-radio-label ternary-default">{none_text}</span>
                </label>
            ''')
        
        html.append('</div>')

        return Markup(''.join(html))

class TernaryNoneBooleanField(Field):
    """
    A field that can handle True, False, or None values, represented as a horizontal radio group.
    When boolean_mode=True, it acts like a BooleanField (only Yes/No options).
    When boolean_mode=False (default), it shows Yes/No/Default options.
    
    Custom text can be provided for each option:
    - yes_text: Text for True option (default: "Yes")
    - no_text: Text for False option (default: "No")  
    - none_text: Text for None option (default: "Default")
    """
    widget = TernaryNoneBooleanWidget()
    
    def __init__(self, label=None, validators=None, false_values=None, boolean_mode=False,
                 yes_text=None, no_text=None, none_text=None, **kwargs):
        super(TernaryNoneBooleanField, self).__init__(label, validators, **kwargs)
        
        self.boolean_mode = boolean_mode
        self.yes_text = yes_text if yes_text is not None else _l('Yes')
        self.no_text = no_text if no_text is not None else _l('No')
        self.none_text = none_text if none_text is not None else _l('Main settings')
        
        if false_values is None:
            self.false_values = {'false', ''}
        else:
            self.false_values = false_values

    def process_formdata(self, valuelist):
        if not valuelist or not valuelist[0]:
            # In boolean mode, default to False instead of None
            self.data = False if self.boolean_mode else None
        elif valuelist[0].lower() == 'true':
            self.data = True
        elif valuelist[0].lower() == 'false':
            self.data = False
        elif valuelist[0].lower() == 'none':
            # In boolean mode, treat 'none' as False
            self.data = False if self.boolean_mode else None
        else:
            self.data = False if self.boolean_mode else None

    def _value(self):
        if self.data is True:
            return 'true'
        elif self.data is False:
            return 'false'
        else:
            # In boolean mode, None should be treated as False
            if self.boolean_mode:
                return 'false'
            else:
                return 'none'