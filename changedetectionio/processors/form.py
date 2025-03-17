from wtforms import (
    BooleanField,
    validators,
    RadioField
)
from wtforms.fields.choices import SelectField
from wtforms.fields.form import FormField
from wtforms.form import Form

class BaseProcessorForm(Form):
    """Base class for processor forms"""
    
    def extra_tab_content(self):
        return None

    def extra_form_content(self):
        return None