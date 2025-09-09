from wtforms import Field
from wtforms import widgets
from markupsafe import Markup

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
        yes_text = getattr(field, 'yes_text', 'Yes')
        no_text = getattr(field, 'no_text', 'No')
        none_text = getattr(field, 'none_text', 'Default')
        
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
        
        # Add CSS styles
        html.append('''
            <style>
                .ternary-radio-group {
                    display: flex;
                    gap: 0;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                    overflow: hidden;
                    width: fit-content;
                    background: #fff;
                }
                
                .ternary-radio-option {
                    position: relative;
                    cursor: pointer;
                    margin: 0;
                    display: flex;
                    align-items: center;
                }
                
                .ternary-radio-option input[type="radio"] {
                    position: absolute;
                    opacity: 0;
                    width: 0;
                    height: 0;
                }
                
                .ternary-radio-label {
                    padding: 8px 16px;
                    background: #f7f7f7;
                    border: none;
                    border-right: 1px solid #ddd;
                    font-size: 13px;
                    font-weight: 500;
                    color: #333;
                    transition: all 0.2s ease;
                    cursor: pointer;
                    display: block;
                    min-width: 60px;
                    text-align: center;
                }
                
                .ternary-radio-option:last-child .ternary-radio-label {
                    border-right: none;
                }
                
                .ternary-radio-option input:checked + .ternary-radio-label {
                    background: #1f8dd6;
                    color: white;
                    font-weight: 600;
                }
                
                .ternary-radio-option input:checked + .ternary-radio-label.ternary-default {
                    background: #999;
                    color: white;
                }
                
                .ternary-radio-option:hover .ternary-radio-label {
                    background: #e6e6e6;
                }
                
                .ternary-radio-option input:checked + .ternary-radio-label:hover {
                    background: #1a7bc4;
                }
                
                .ternary-radio-option input:checked + .ternary-radio-label.ternary-default:hover {
                    background: #777;
                }
                
                @media (max-width: 480px) {
                    .ternary-radio-group {
                        width: 100%;
                    }
                    
                    .ternary-radio-label {
                        flex: 1;
                        min-width: auto;
                    }
                }
            </style>
        ''')
        
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
                 yes_text="Yes", no_text="No", none_text="Default", **kwargs):
        super(TernaryNoneBooleanField, self).__init__(label, validators, **kwargs)
        
        self.boolean_mode = boolean_mode
        self.yes_text = yes_text
        self.no_text = no_text
        self.none_text = none_text
        
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