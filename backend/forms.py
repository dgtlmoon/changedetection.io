from wtforms import Form, BooleanField, StringField, PasswordField, validators, IntegerField, fields, TextAreaField, \
    Field
from wtforms import widgets
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


class watchForm(Form):
    # https://wtforms.readthedocs.io/en/2.3.x/fields/#module-wtforms.fields.html5
    # `require_tld` = False is needed even for the test harness "http://localhost:5005.." to run

    url = html5.URLField('URL', [validators.URL(require_tld=False)])
    tag = StringField('Tag', [validators.Optional(), validators.Length(max=35)])
    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.Optional(), validators.NumberRange(min=1)])
    css_filter = StringField('CSS Filter')

    ignore_text = StringListField('Ignore Text')
    notification_urls = StringListField('Notification URL List')
    headers = StringDictKeyValue('Request Headers')
    trigger_check = BooleanField('Send test notification on save')


class globalSettingsForm(Form):

    password = PasswordField()
    remove_password = BooleanField('Remove password')

    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.Optional(), validators.NumberRange(min=1)])
    notification_urls = StringListField('Notification URL List')
    trigger_check = BooleanField('Send test notification on save')
