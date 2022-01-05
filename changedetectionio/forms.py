from wtforms import Form, SelectField, RadioField, BooleanField, StringField, PasswordField, validators, IntegerField, fields, TextAreaField, \
    Field
from wtforms import widgets
from wtforms.validators import ValidationError
from wtforms.fields import html5
from changedetectionio import content_fetcher
import re

from changedetectionio.notification import default_notification_format, valid_notification_formats, default_notification_body, default_notification_title

valid_method = {
    'GET',
    'POST',
    'PUT',
    'PATCH',
    'DELETE',
}

default_method = 'GET'

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
            # Be really sure it's non-zero in length
            if len(valuelist[0].strip()) > 0:
                self.encrypted_password = self.build_password(valuelist[0])
                self.data = ""
        else:
            self.data = False


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
                parts = s.strip().split(':', 1)
                if len(parts) == 2:
                    self.data.update({parts[0].strip(): parts[1].strip()})

        else:
            self.data = {}

class ValidateContentFetcherIsReady(object):
    """
    Validates that anything that looks like a regex passes as a regex
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        from changedetectionio import content_fetcher
        import urllib3.exceptions

        # Better would be a radiohandler that keeps a reference to each class
        if field.data is not None:
            klass = getattr(content_fetcher, field.data)
            some_object = klass()
            try:
                ready = some_object.is_ready()

            except urllib3.exceptions.MaxRetryError as e:
                driver_url = some_object.command_executor
                message = field.gettext('Content fetcher \'%s\' did not respond.' % (field.data))
                message += '<br/>' + field.gettext(
                    'Be sure that the selenium/webdriver runner is running and accessible via network from this container/host.')
                message += '<br/>' + field.gettext('Did you follow the instructions in the wiki?')
                message += '<br/><br/>' + field.gettext('WebDriver Host: %s' % (driver_url))
                message += '<br/><a href="https://github.com/dgtlmoon/changedetection.io/wiki/Fetching-pages-with-WebDriver">Go here for more information</a>'
                message += '<br/>'+field.gettext('Content fetcher did not respond properly, unable to use it.\n %s' % (str(e)))

                raise ValidationError(message)

            except Exception as e:
                message = field.gettext('Content fetcher \'%s\' did not respond properly, unable to use it.\n %s')
                raise ValidationError(message % (field.data, e))


class ValidateAppRiseServers(object):
    """
       Validates that each URL given is compatible with AppRise
       """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        import apprise
        apobj = apprise.Apprise()

        for server_url in field.data:
            if not apobj.add(server_url):
                message = field.gettext('\'%s\' is not a valid AppRise URL.' % (server_url))
                raise ValidationError(message)

class ValidateTokensList(object):
    """
    Validates that a {token} is from a valid set
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        from changedetectionio import notification
        regex = re.compile('{.*?}')
        for p in re.findall(regex, field.data):
            if not p.strip('{}') in notification.valid_tokens:
                message = field.gettext('Token \'%s\' is not a valid token.')
                raise ValidationError(message % (p))

class ValidateListRegex(object):
    """
    Validates that anything that looks like a regex passes as a regex
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):

        for line in field.data:
            if line[0] == '/' and line[-1] == '/':
                # Because internally we dont wrap in /
                line = line.strip('/')
                try:
                    re.compile(line)
                except re.error:
                    message = field.gettext('RegEx \'%s\' is not a valid regular expression.')
                    raise ValidationError(message % (line))

class ValidateCSSJSONXPATHInput(object):
    """
    Filter validation
    @todo CSS validator ;)
    """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):

        # Nothing to see here
        if not len(field.data.strip()):
            return

        # Does it look like XPath?
        if field.data.strip()[0] == '/':
            from lxml import html, etree
            tree = html.fromstring("<html></html>")

            try:
                tree.xpath(field.data.strip())
            except etree.XPathEvalError as e:
                message = field.gettext('\'%s\' is not a valid XPath expression. (%s)')
                raise ValidationError(message % (field.data, str(e)))
            except:
                raise ValidationError("A system-error occurred when validating your XPath expression")

        if 'json:' in field.data:
            from jsonpath_ng.exceptions import JsonPathParserError, JsonPathLexerError
            from jsonpath_ng.ext import parse

            input = field.data.replace('json:', '')

            try:
                parse(input)
            except (JsonPathParserError, JsonPathLexerError) as e:
                message = field.gettext('\'%s\' is not a valid JSONPath expression. (%s)')
                raise ValidationError(message % (input, str(e)))
            except:
                raise ValidationError("A system-error occurred when validating your JSONPath expression")

            # Re #265 - maybe in the future fetch the page and offer a
            # warning/notice that its possible the rule doesnt yet match anything?

class quickWatchForm(Form):
    # https://wtforms.readthedocs.io/en/2.3.x/fields/#module-wtforms.fields.html5
    # `require_tld` = False is needed even for the test harness "http://localhost:5005.." to run
    url = html5.URLField('URL', [validators.URL(require_tld=False)])
    tag = StringField('Group tag', [validators.Optional(), validators.Length(max=35)])

class commonSettingsForm(Form):

    notification_urls = StringListField('Notification URL List', validators=[validators.Optional(), ValidateAppRiseServers()])
    notification_title = StringField('Notification Title', default=default_notification_title, validators=[validators.Optional(), ValidateTokensList()])
    notification_body = TextAreaField('Notification Body', default=default_notification_body, validators=[validators.Optional(), ValidateTokensList()])
    notification_format = SelectField('Notification Format', choices=valid_notification_formats.keys(), default=default_notification_format)
    trigger_check = BooleanField('Send test notification on save')
    fetch_backend = RadioField(u'Fetch Method', choices=content_fetcher.available_fetchers(), validators=[ValidateContentFetcherIsReady()])
    extract_title_as_title = BooleanField('Extract <title> from document and use as watch title', default=False)

class watchForm(commonSettingsForm):

    url = html5.URLField('URL', [validators.URL(require_tld=False)])
    tag = StringField('Group tag', [validators.Optional(), validators.Length(max=35)])

    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.Optional(), validators.NumberRange(min=1)])
    css_filter = StringField('CSS/JSON/XPATH Filter', [ValidateCSSJSONXPATHInput()])
    title = StringField('Title')

    ignore_text = StringListField('Ignore Text', [ValidateListRegex()])
    headers = StringDictKeyValue('Request Headers')
    body = TextAreaField('Request Body', [validators.Optional()])
    method = SelectField('Request Method', choices=valid_method, default=default_method)
    trigger_text = StringListField('Trigger/wait for text', [validators.Optional(), ValidateListRegex()])

    def validate(self, **kwargs):
        if not super().validate():
            return False

        result = True

        # Fail form validation when a body is set for a GET
        if self.method.data == 'GET' and self.body.data:
            self.body.errors.append('Body must be empty when Request Method is set to GET')
            result = False

        return result

class globalSettingsForm(commonSettingsForm):

    password = SaltyPasswordField()
    minutes_between_check = html5.IntegerField('Maximum time in minutes until recheck',
                                               [validators.NumberRange(min=1)])
    extract_title_as_title = BooleanField('Extract <title> from document and use as watch title')
    base_url = StringField('Base URL', validators=[validators.Optional()])
    global_ignore_text = StringListField('Ignore Text', [ValidateListRegex()])
    ignore_whitespace = BooleanField('Ignore whitespace')