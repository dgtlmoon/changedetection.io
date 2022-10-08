import re

from wtforms import (
    BooleanField,
    Field,
    Form,
    IntegerField,
    PasswordField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    fields,
    validators,
    widgets,
)
from wtforms.validators import ValidationError

from changedetectionio import content_fetcher
from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
    valid_notification_formats,
)

from wtforms.fields import FormField

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
            # ignore empty lines in the storage
            data = list(filter(lambda x: len(x.strip()), self.data))
            # Apply strip to each line
            data = list(map(lambda x: x.strip(), data))
            return "\r\n".join(data)
        else:
            return u''

    # incoming
    def process_formdata(self, valuelist):
        if valuelist and len(valuelist[0].strip()):
            # Remove empty strings, stripping and splitting \r\n, only \n etc.
            self.data = valuelist[0].splitlines()
            # Remove empty lines from the final data
            self.data = list(filter(lambda x: len(x.strip()), self.data))
        else:
            self.data = []


class SaltyPasswordField(StringField):
    widget = widgets.PasswordInput()
    encrypted_password = ""

    def build_password(self, password):
        import base64
        import hashlib
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

class TimeBetweenCheckForm(Form):
    weeks = IntegerField('Weeks', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
    days = IntegerField('Days', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
    hours = IntegerField('Hours', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
    minutes = IntegerField('Minutes', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
    seconds = IntegerField('Seconds', validators=[validators.Optional(), validators.NumberRange(min=0, message="Should contain zero or more seconds")])
    # @todo add total seconds minimum validatior = minimum_seconds_recheck_time

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
        import urllib3.exceptions
        from changedetectionio import content_fetcher

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


class ValidateNotificationBodyAndTitleWhenURLisSet(object):
    """
       Validates that they entered something in both notification title+body when the URL is set
       Due to https://github.com/dgtlmoon/changedetection.io/issues/360
       """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        if len(field.data):
            if not len(form.notification_title.data) or not len(form.notification_body.data):
                message = field.gettext('Notification Body and Title is required when a Notification URL is used')
                raise ValidationError(message)

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
            
class validateURL(object):
    
    """
       Flask wtform validators wont work with basic auth
    """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        import validators
        try:
            validators.url(field.data.strip())
        except validators.ValidationFailure:
            message = field.gettext('\'%s\' is not a valid URL.' % (field.data.strip()))
            raise ValidationError(message)

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

    def __init__(self, message=None, allow_xpath=True, allow_json=True):
        self.message = message
        self.allow_xpath = allow_xpath
        self.allow_json = allow_json

    def __call__(self, form, field):

        if isinstance(field.data, str):
            data = [field.data]
        else:
            data = field.data

        for line in data:
        # Nothing to see here
            if not len(line.strip()):
                return

            # Does it look like XPath?
            if line.strip()[0] == '/':
                if not self.allow_xpath:
                    raise ValidationError("XPath not permitted in this field!")
                from lxml import etree, html
                tree = html.fromstring("<html></html>")

                try:
                    tree.xpath(line.strip())
                except etree.XPathEvalError as e:
                    message = field.gettext('\'%s\' is not a valid XPath expression. (%s)')
                    raise ValidationError(message % (line, str(e)))
                except:
                    raise ValidationError("A system-error occurred when validating your XPath expression")

            if 'json:' in line:
                if not self.allow_json:
                    raise ValidationError("JSONPath not permitted in this field!")

                from jsonpath_ng.exceptions import (
                    JsonPathLexerError,
                    JsonPathParserError,
                )
                from jsonpath_ng.ext import parse

                input = line.replace('json:', '')

                try:
                    parse(input)
                except (JsonPathParserError, JsonPathLexerError) as e:
                    message = field.gettext('\'%s\' is not a valid JSONPath expression. (%s)')
                    raise ValidationError(message % (input, str(e)))
                except:
                    raise ValidationError("A system-error occurred when validating your JSONPath expression")

                # Re #265 - maybe in the future fetch the page and offer a
                # warning/notice that its possible the rule doesnt yet match anything?

            if 'jq:' in line:
                if not self.allow_json:
                    raise ValidationError("jq not permitted in this field!")

                import jq
                input = line.replace('jq:', '')

                try:
                    jq.compile(input)
                except (ValueError) as e:
                    message = field.gettext('\'%s\' is not a valid jq expression. (%s)')
                    raise ValidationError(message % (input, str(e)))
                except:
                    raise ValidationError("A system-error occurred when validating your jq expression")


class quickWatchForm(Form):
    url = fields.URLField('URL', validators=[validateURL()])
    tag = StringField('Group tag', [validators.Optional()])
    watch_submit_button = SubmitField('Watch', render_kw={"class": "pure-button pure-button-primary"})
    edit_and_watch_submit_button = SubmitField('Edit > Watch', render_kw={"class": "pure-button pure-button-primary"})


# Common to a single watch and the global settings
class commonSettingsForm(Form):
    notification_urls = StringListField('Notification URL list', validators=[validators.Optional(), ValidateAppRiseServers()])
    notification_title = StringField('Notification title', validators=[validators.Optional(), ValidateTokensList()])
    notification_body = TextAreaField('Notification body', validators=[validators.Optional(), ValidateTokensList()])
    notification_format = SelectField('Notification format', choices=valid_notification_formats.keys())
    fetch_backend = RadioField(u'Fetch method', choices=content_fetcher.available_fetchers(), validators=[ValidateContentFetcherIsReady()])
    extract_title_as_title = BooleanField('Extract <title> from document and use as watch title', default=False)
    webdriver_delay = IntegerField('Wait seconds before extracting text', validators=[validators.Optional(), validators.NumberRange(min=1,
                                                                                                                                    message="Should contain one or more seconds")])

class watchForm(commonSettingsForm):

    url = fields.URLField('URL', validators=[validateURL()])
    tag = StringField('Group tag', [validators.Optional()], default='')

    time_between_check = FormField(TimeBetweenCheckForm)

    css_filter = StringField('CSS/JSON/XPATH Filter', [ValidateCSSJSONXPATHInput()], default='')

    subtractive_selectors = StringListField('Remove elements', [ValidateCSSJSONXPATHInput(allow_xpath=False, allow_json=False)])

    extract_text = StringListField('Extract text', [ValidateListRegex()])

    title = StringField('Title', default='')

    ignore_text = StringListField('Ignore text', [ValidateListRegex()])
    headers = StringDictKeyValue('Request headers')
    body = TextAreaField('Request body', [validators.Optional()])
    method = SelectField('Request method', choices=valid_method, default=default_method)
    ignore_status_codes = BooleanField('Ignore status codes (process non-2xx status codes as normal)', default=False)
    check_unique_lines = BooleanField('Only trigger when new lines appear', default=False)
    trigger_text = StringListField('Trigger/wait for text', [validators.Optional(), ValidateListRegex()])
    text_should_not_be_present = StringListField('Block change-detection if text matches', [validators.Optional(), ValidateListRegex()])

    webdriver_js_execute_code = TextAreaField('Execute JavaScript before change detection', render_kw={"rows": "5"}, validators=[validators.Optional()])

    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})

    proxy = RadioField('Proxy')
    filter_failure_notification_send = BooleanField(
        'Send a notification when the filter can no longer be found on the page', default=False)

    notification_muted = BooleanField('Notifications Muted / Off', default=False)

    def validate(self, **kwargs):
        if not super().validate():
            return False

        result = True

        # Fail form validation when a body is set for a GET
        if self.method.data == 'GET' and self.body.data:
            self.body.errors.append('Body must be empty when Request Method is set to GET')
            result = False

        return result


# datastore.data['settings']['requests']..
class globalSettingsRequestForm(Form):
    time_between_check = FormField(TimeBetweenCheckForm)
    proxy = RadioField('Proxy')
    jitter_seconds = IntegerField('Random jitter seconds ± check',
                                  render_kw={"style": "width: 5em;"},
                                  validators=[validators.NumberRange(min=0, message="Should contain zero or more seconds")])

# datastore.data['settings']['application']..
class globalSettingsApplicationForm(commonSettingsForm):

    base_url = StringField('Base URL', validators=[validators.Optional()])
    global_subtractive_selectors = StringListField('Remove elements', [ValidateCSSJSONXPATHInput(allow_xpath=False, allow_json=False)])
    global_ignore_text = StringListField('Ignore Text', [ValidateListRegex()])
    ignore_whitespace = BooleanField('Ignore whitespace')
    removepassword_button = SubmitField('Remove password', render_kw={"class": "pure-button pure-button-primary"})
    empty_pages_are_a_change =  BooleanField('Treat empty pages as a change?', default=False)
    render_anchor_tag_content = BooleanField('Render anchor tag content', default=False)
    fetch_backend = RadioField('Fetch Method', default="html_requests", choices=content_fetcher.available_fetchers(), validators=[ValidateContentFetcherIsReady()])
    api_access_token_enabled = BooleanField('API access token security check enabled', default=True, validators=[validators.Optional()])
    password = SaltyPasswordField()

    filter_failure_notification_threshold_attempts = IntegerField('Number of times the filter can be missing before sending a notification',
                                                                  render_kw={"style": "width: 5em;"},
                                                                  validators=[validators.NumberRange(min=0,
                                                                                                     message="Should contain zero or more attempts")])


class globalSettingsForm(Form):
    # Define these as FormFields/"sub forms", this way it matches the JSON storage
    # datastore.data['settings']['application']..
    # datastore.data['settings']['requests']..

    requests = FormField(globalSettingsRequestForm)
    application = FormField(globalSettingsApplicationForm)
    save_button = SubmitField('Save', render_kw={"class": "pure-button pure-button-primary"})
