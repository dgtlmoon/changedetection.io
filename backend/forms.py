from wtforms import Form, BooleanField, StringField, PasswordField, validators, IntegerField, fields, TextAreaField, \
    Field
from wtforms import widgets
from wtforms.validators import ValidationError
from wtforms.fields import html5


class StringListField(StringField):
    widget = widgets.TextArea()

    def _value(self):
        if self.data:
            return "\r\n".join(self.data)
        else:
            return u''

    # incoming
    def process_formdata(self, valuelist):
        if valuelist:
            # Remove empty strings
            cleaned = list(filter(None, valuelist[0].split("\n")))
            self.data = [x.strip() for x in cleaned]
            p = 1
        else:
            self.data = []



class SaltyPasswordField(StringField):
    widget = widgets.PasswordInput()
    encrypted_password = ""

    def build_password(self, password):
        import hashlib
        import base64
        import secrets

        # Make a new salt on every new password and store it with the password
        salt = secrets.token_bytes(32)

        key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        store = base64.b64encode(salt + key).decode('ascii')

        return store

    # incoming
    def process_formdata(self, valuelist):
        if valuelist:
            # Remove empty strings
            self.encrypted_password = self.build_password(valuelist[0])
            self.data = []
        else:
            self.data = []


# Separated by  key:value
class StringDictKeyValue(StringField):
    widget = widgets.TextArea()

    def _value(self):
        if self.data:
            output = u''
            for k in self.data.keys():
                output += "{}: {}\r\n".format(k, self.data[k])

            return output
        else:
            return u''

    # incoming
    def process_formdata(self, valuelist):
        if valuelist:
            self.data = {}
            # Remove empty strings
            cleaned = list(filter(None, valuelist[0].split("\n")))
            for s in cleaned:
                parts = s.strip().split(':')
                if len(parts) == 2:
                    self.data.update({parts[0].strip(): parts[1].strip()})

        else:
            self.data = {}

class ListRegex(object):
    """
    Validates that anything that looks like a regex passes as a regex
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        import re

        for line in field.data:
            if line[0] == '/' and line[-1] == '/':
                # Because internally we dont wrap in /
                line = line.strip('/')
                try:
                    re.compile(line)
                except re.error:
                    message = field.gettext('RegEx \'%s\' is not a valid regular expression.')
                    raise ValidationError(message % (line))


class watchForm(Form):
    # https://wtforms.readthedocs.io/en/2.3.x/fields/#module-wtforms.fields.html5
    # `require_tld` = False is needed even for the test harness "http://localhost:5005.." to run

    url = html5.URLField('URL', [validators.URL(require_tld=False)])
    tag = StringField('Tag', [validators.Optional(), validators.Length(max=35)])
    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.Optional(), validators.NumberRange(min=1)])
    css_filter = StringField('CSS Filter')

    ignore_text = StringListField('Ignore Text', [ListRegex()])
    notification_urls = StringListField('Notification URL List')
    headers = StringDictKeyValue('Request Headers')
    trigger_check = BooleanField('Send test notification on save')


class globalSettingsForm(Form):

    password = SaltyPasswordField()
    remove_password = BooleanField('Remove password')

    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.NumberRange(min=1)])

    notification_urls = StringListField('Notification URL List')
    trigger_check = BooleanField('Send test notification on save')
