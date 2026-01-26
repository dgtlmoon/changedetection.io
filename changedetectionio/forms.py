import os
import re
from loguru import logger
from wtforms.widgets.core import TimeInput
from flask_babel import lazy_gettext as _l, gettext

from changedetectionio.blueprint.rss import RSS_FORMAT_TYPES, RSS_TEMPLATE_TYPE_OPTIONS, RSS_TEMPLATE_HTML_DEFAULT
from changedetectionio.conditions.form import ConditionFormRow
from changedetectionio.notification_service import NotificationContextData
from changedetectionio.processors.image_ssim_diff import SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS, \
    SCREENSHOT_COMPARISON_THRESHOLD_OPTIONS_DEFAULT
from changedetectionio.strtobool import strtobool
from changedetectionio import processors

from wtforms import (
    BooleanField,
    Form,
    Field,
    FloatField,
    IntegerField,
    RadioField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    fields,
    validators,
    widgets
)
from flask_wtf.file import FileField, FileAllowed
from wtforms.fields import FieldList
from wtforms.utils import unset_value

from wtforms.validators import ValidationError

from changedetectionio.widgets import TernaryNoneBooleanField

# default
# each select <option data-enabled="enabled-0-0"
from changedetectionio.blueprint.browser_steps.browser_steps import browser_step_ui_config

from changedetectionio import html_tools, content_fetchers

from changedetectionio.notification import (
    valid_notification_formats,
)

from wtforms.fields import FormField

dictfilt = lambda x, y: dict([ (i,x[i]) for i in x if i in set(y) ])

valid_method = {
    'GET',
    'POST',
    'PUT',
    'PATCH',
    'DELETE',
    'OPTIONS',
}

default_method = 'GET'
allow_simplehost = not strtobool(os.getenv('BLOCK_SIMPLEHOSTS', 'False'))
REQUIRE_ATLEAST_ONE_TIME_PART_MESSAGE_DEFAULT=_l('At least one time interval (weeks, days, hours, minutes, or seconds) must be specified.')
REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT=_l('At least one time interval (weeks, days, hours, minutes, or seconds) must be specified when not using global settings.')

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

class StringTagUUID(StringField):

   # process_formdata(self, valuelist) handled manually in POST handler

    # Is what is shown when field <input> is rendered
    def _value(self):
        # Tag UUID to name, on submit it will convert it back (in the submit handler of init.py)
        if self.data and type(self.data) is list:
            tag_titles = []
            for i in self.data:
                tag = self.datastore.data['settings']['application']['tags'].get(i)
                if tag:
                    tag_title = tag.get('title')
                    if tag_title:
                        tag_titles.append(tag_title)

            return ', '.join(tag_titles)

        if not self.data:
            return ''

        return 'error'

class TimeDurationForm(Form):
    hours = SelectField(choices=[(f"{i}", f"{i}") for i in range(0, 25)], default="24",  validators=[validators.Optional()])
    minutes = SelectField(choices=[(f"{i}", f"{i}") for i in range(0, 60)], default="00", validators=[validators.Optional()])

class TimeStringField(Field):
    """
    A WTForms field for time inputs (HH:MM) that stores the value as a string.
    """
    widget = TimeInput()  # Use the built-in time input widget

    def _value(self):
        """
        Returns the value for rendering in the form.
        """
        return self.data if self.data is not None else ""

    def process_formdata(self, valuelist):
        """
        Processes the raw input from the form and stores it as a string.
        """
        if valuelist:
            time_str = valuelist[0]
            # Simple validation for HH:MM format
            if not time_str or len(time_str.split(":")) != 2:
                raise ValidationError(_l("Invalid time format. Use HH:MM."))
            self.data = time_str


class validateTimeZoneName(object):
    """
       Flask wtform validators wont work with basic auth
    """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        from zoneinfo import available_timezones
        python_timezones = available_timezones()
        if field.data and field.data not in python_timezones:
            raise ValidationError(_l("Not a valid timezone name"))

class ScheduleLimitDaySubForm(Form):
    enabled = BooleanField(_l("not set"), default=True)
    start_time = TimeStringField(_l("Start At"), default="00:00", validators=[validators.Optional()])
    duration = FormField(TimeDurationForm, label=_l("Run duration"))

class ScheduleLimitForm(Form):
    enabled = BooleanField(_l("Use time scheduler"), default=False)
    # Because the label for=""" doesnt line up/work with the actual checkbox
    monday = FormField(ScheduleLimitDaySubForm, label="")
    tuesday = FormField(ScheduleLimitDaySubForm, label="")
    wednesday = FormField(ScheduleLimitDaySubForm, label="")
    thursday = FormField(ScheduleLimitDaySubForm, label="")
    friday = FormField(ScheduleLimitDaySubForm, label="")
    saturday = FormField(ScheduleLimitDaySubForm, label="")
    sunday = FormField(ScheduleLimitDaySubForm, label="")

    timezone = StringField(_l("Optional timezone to run in"),
                                  render_kw={"list": "timezones"},
                                  validators=[validateTimeZoneName()]
                                  )
    def __init__(
        self,
        formdata=None,
        obj=None,
        prefix="",
        data=None,
        meta=None,
        **kwargs,
    ):
        super().__init__(formdata, obj, prefix, data, meta, **kwargs)
        self.monday.form.enabled.label.text=_l("Monday")
        self.tuesday.form.enabled.label.text = _l("Tuesday")
        self.wednesday.form.enabled.label.text = _l("Wednesday")
        self.thursday.form.enabled.label.text = _l("Thursday")
        self.friday.form.enabled.label.text = _l("Friday")
        self.saturday.form.enabled.label.text = _l("Saturday")
        self.sunday.form.enabled.label.text = _l("Sunday")


def validate_time_between_check_has_values(form):
    """
    Custom validation function for TimeBetweenCheckForm.
    Returns True if at least one time interval field has a value > 0.
    """
    res = any([
        form.weeks.data and int(form.weeks.data) > 0,
        form.days.data and int(form.days.data) > 0,
        form.hours.data and int(form.hours.data) > 0,
        form.minutes.data and int(form.minutes.data) > 0,
        form.seconds.data and int(form.seconds.data) > 0
    ])

    return res


class RequiredTimeInterval(object):
    """
    WTForms validator that ensures at least one time interval field has a value > 0.
    Use this with FormField(TimeBetweenCheckForm, validators=[RequiredTimeInterval()]).
    """
    def __init__(self, message=None):
        self.message = message or _l('At least one time interval (weeks, days, hours, minutes, or seconds) must be specified.')

    def __call__(self, form, field):
        if not validate_time_between_check_has_values(field.form):
            raise ValidationError(self.message)


class TimeBetweenCheckForm(Form):
    weeks = IntegerField(_l('Weeks'), validators=[validators.Optional(), validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    days = IntegerField(_l('Days'), validators=[validators.Optional(), validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    hours = IntegerField(_l('Hours'), validators=[validators.Optional(), validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    minutes = IntegerField(_l('Minutes'), validators=[validators.Optional(), validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    seconds = IntegerField(_l('Seconds'), validators=[validators.Optional(), validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    # @todo add total seconds minimum validatior = minimum_seconds_recheck_time

    def __init__(self, formdata=None, obj=None, prefix="", data=None, meta=None, **kwargs):
        super().__init__(formdata, obj, prefix, data, meta, **kwargs)
        self.require_at_least_one = kwargs.get('require_at_least_one', False)
        self.require_at_least_one_message = kwargs.get('require_at_least_one_message', REQUIRE_ATLEAST_ONE_TIME_PART_MESSAGE_DEFAULT)

    def validate(self, **kwargs):
        """Custom validation that can optionally require at least one time interval."""
        # Run normal field validation first
        if not super().validate(**kwargs):
            return False

        # Apply optional "at least one" validation
        if self.require_at_least_one:
            if not validate_time_between_check_has_values(self):
                # Add error to the form's general errors (not field-specific)
                if not hasattr(self, '_formdata_errors'):
                    self._formdata_errors = []
                self._formdata_errors.append(self.require_at_least_one_message)
                return False

        return True


class EnhancedFormField(FormField):
    """
    An enhanced FormField that supports conditional validation with top-level error messages.
    Adds a 'top_errors' property for validation errors at the FormField level.
    """

    def __init__(self, form_class, label=None, validators=None, separator="-",
                 conditional_field=None, conditional_message=None, conditional_test_function=None, **kwargs):
        """
        Initialize EnhancedFormField with optional conditional validation.

        :param conditional_field: Name of the field this FormField depends on (e.g. 'time_between_check_use_default')
        :param conditional_message: Error message to show when validation fails
        :param conditional_test_function: Custom function to test if FormField has valid values.
                                        Should take self.form as parameter and return True if valid.
        """
        super().__init__(form_class, label, validators, separator, **kwargs)
        self.top_errors = []
        self.conditional_field = conditional_field
        self.conditional_message = conditional_message or "At least one field must have a value when not using defaults."
        self.conditional_test_function = conditional_test_function

    def validate(self, form, extra_validators=()):
        """
        Custom validation that supports conditional logic and stores top-level errors.
        """
        self.top_errors = []

        # First run the normal FormField validation
        base_valid = super().validate(form, extra_validators)

        # Apply conditional validation if configured
        if self.conditional_field and hasattr(form, self.conditional_field):
            conditional_field_obj = getattr(form, self.conditional_field)

            # If the conditional field is False/unchecked, check if this FormField has any values
            if not conditional_field_obj.data:
                # Use custom test function if provided, otherwise use generic fallback
                if self.conditional_test_function:
                    has_any_value = self.conditional_test_function(self.form)
                else:
                    # Generic fallback - check if any field has truthy data
                    has_any_value = any(field.data for field in self.form if hasattr(field, 'data') and field.data)

                if not has_any_value:
                    self.top_errors.append(self.conditional_message)
                    base_valid = False

        return base_valid


class RequiredFormField(FormField):
    """
    A FormField that passes require_at_least_one=True to TimeBetweenCheckForm.
    Use this when you want the sub-form to always require at least one value.
    """

    def __init__(self, form_class, label=None, validators=None, separator="-", **kwargs):
        super().__init__(form_class, label, validators, separator, **kwargs)

    def process(self, formdata, data=unset_value, extra_filters=None):
        if extra_filters:
            raise TypeError(
                "FormField cannot take filters, as the encapsulated"
                "data is not mutable."
            )

        if data is unset_value:
            try:
                data = self.default()
            except TypeError:
                data = self.default
            self._obj = data

        self.object_data = data

        prefix = self.name + self.separator
        # Pass require_at_least_one=True to the sub-form
        if isinstance(data, dict):
            self.form = self.form_class(formdata=formdata, prefix=prefix, require_at_least_one=True, **data)
        else:
            self.form = self.form_class(formdata=formdata, obj=data, prefix=prefix, require_at_least_one=True)

    @property
    def errors(self):
        """Include sub-form validation errors"""
        form_errors = self.form.errors
        # Add any general form errors to a special 'form' key
        if hasattr(self.form, '_formdata_errors') and self.form._formdata_errors:
            form_errors = dict(form_errors)  # Make a copy
            form_errors['form'] = self.form._formdata_errors
        return form_errors


# Separated by  key:value
class StringDictKeyValue(StringField):
    widget = widgets.TextArea()

    def _value(self):
        if self.data:
            output = ''
            for k, v in self.data.items():
                output += f"{k}: {v}\r\n"
            return output
        else:
            return ''

    # incoming data processing + validation
    def process_formdata(self, valuelist):
        self.data = {}
        errors = []
        if valuelist:
            # Remove empty strings (blank lines)
            cleaned = [line.strip() for line in valuelist[0].split("\n") if line.strip()]
            for idx, s in enumerate(cleaned, start=1):
                if ':' not in s:
                    errors.append(f"Line {idx} is missing a ':' separator.")
                    continue
                parts = s.split(':', 1)
                key = parts[0].strip()
                value = parts[1].strip()

                if not key:
                    errors.append(f"Line {idx} has an empty key.")
                if not value:
                    errors.append(f"Line {idx} has an empty value.")

                self.data[key] = value

        if errors:
            raise ValidationError("Invalid input:\n" + "\n".join(errors))

class ValidateContentFetcherIsReady(object):
    """
    Validates that anything that looks like a regex passes as a regex
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        return

# AttributeError: module 'changedetectionio.content_fetcher' has no attribute 'extra_browser_unlocked<>ASDF213r123r'
        # Better would be a radiohandler that keeps a reference to each class
        # if field.data is not None and field.data != 'system':
        #     klass = getattr(content_fetcher, field.data)
        #     some_object = klass()
        #     try:
        #         ready = some_object.is_ready()
        #
        #     except urllib3.exceptions.MaxRetryError as e:
        #         driver_url = some_object.command_executor
        #         message = field.gettext('Content fetcher \'%s\' did not respond.' % (field.data))
        #         message += '<br>' + field.gettext(
        #             'Be sure that the selenium/webdriver runner is running and accessible via network from this container/host.')
        #         message += '<br>' + field.gettext('Did you follow the instructions in the wiki?')
        #         message += '<br><br>' + field.gettext('WebDriver Host: %s' % (driver_url))
        #         message += '<br><a href="https://github.com/dgtlmoon/changedetection.io/wiki/Fetching-pages-with-WebDriver">Go here for more information</a>'
        #         message += '<br>'+field.gettext('Content fetcher did not respond properly, unable to use it.\n %s' % (str(e)))
        #
        #         raise ValidationError(message)
        #
        #     except Exception as e:
        #         message = field.gettext('Content fetcher \'%s\' did not respond properly, unable to use it.\n %s')
        #         raise ValidationError(message % (field.data, e))


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
        from .notification.apprise_plugin.assets import apprise_asset
        from .notification.apprise_plugin.custom_handlers import apprise_http_custom_handler  # noqa: F401
        from changedetectionio.jinja2_custom import render as jinja_render

        apobj = apprise.Apprise(asset=apprise_asset)

        for server_url in field.data:
            generic_notification_context_data = NotificationContextData()
            # Make sure something is atleast in all those regular token fields
            generic_notification_context_data.set_random_for_validation()

            url = jinja_render(template_str=server_url.strip(), **generic_notification_context_data).strip()
            if url.startswith("#"):
                continue

            if not apobj.add(url):
                message = field.gettext('\'%s\' is not a valid AppRise URL.' % (url))
                raise ValidationError(message)

class ValidateJinja2Template(object):
    """
    Validates that a {token} is from a valid set
    """
    def __call__(self, form, field):
        from changedetectionio import notification
        from changedetectionio.jinja2_custom import create_jinja_env
        from jinja2 import BaseLoader, TemplateSyntaxError, UndefinedError
        from jinja2.meta import find_undeclared_variables
        import jinja2.exceptions

        # Might be a list of text, or might be just text (like from the apprise url list)
        joined_data = ' '.join(map(str, field.data)) if isinstance(field.data, list) else f"{field.data}"

        try:
            # Use the shared helper to create a properly configured environment
            jinja2_env = create_jinja_env(loader=BaseLoader)

            # Add notification tokens for validation
            static_token_placeholders = NotificationContextData()
            static_token_placeholders.set_random_for_validation()
            jinja2_env.globals.update(static_token_placeholders)
            if hasattr(field, 'extra_notification_tokens'):
                jinja2_env.globals.update(field.extra_notification_tokens)

            jinja2_env.from_string(joined_data).render()
        except TemplateSyntaxError as e:
            raise ValidationError(f"This is not a valid Jinja2 template: {e}") from e
        except UndefinedError as e:
            raise ValidationError(f"A variable or function is not defined: {e}") from e
        except jinja2.exceptions.SecurityError as e:
            raise ValidationError(f"This is not a valid Jinja2 template: {e}") from e

        # Check for undeclared variables
        ast = jinja2_env.parse(joined_data)
        undefined = ", ".join(find_undeclared_variables(ast))
        if undefined:
            raise ValidationError(
                f"The following tokens used in the notification are not valid: {undefined}"
            )

class validateURL(object):

    """
       Flask wtform validators wont work with basic auth
    """

    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        # This should raise a ValidationError() or not
        validate_url(field.data)


def validate_url(test_url):
    from changedetectionio.validate_url import is_safe_valid_url
    if not is_safe_valid_url(test_url):
        # This should be wtforms.validators.
        raise ValidationError('Watch protocol is not permitted or invalid URL format')


class ValidateSinglePythonRegexString(object):
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):
        try:
            re.compile(field.data)
        except re.error:
            message = field.gettext('RegEx \'%s\' is not a valid regular expression.')
            raise ValidationError(message % (field.data))


class ValidateListRegex(object):
    """
    Validates that anything that looks like a regex passes as a regex
    """
    def __init__(self, message=None):
        self.message = message

    def __call__(self, form, field):

        for line in field.data:
            if re.search(html_tools.PERL_STYLE_REGEX, line, re.IGNORECASE):
                try:
                    regex = html_tools.perl_style_slash_enclosed_regex_to_options(line)
                    re.compile(regex)
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
            if line.strip()[0] == '/' or line.strip().startswith('xpath:'):
                if not self.allow_xpath:
                    raise ValidationError("XPath not permitted in this field!")
                from lxml import etree, html
                import elementpath
                # xpath 2.0-3.1
                from elementpath.xpath3 import XPath3Parser
                tree = html.fromstring("<html></html>")
                line = line.replace('xpath:', '')

                try:
                    elementpath.select(tree, line.strip(), parser=XPath3Parser)
                except elementpath.ElementPathError as e:
                    message = field.gettext('\'%s\' is not a valid XPath expression. (%s)')
                    raise ValidationError(message % (line, str(e)))
                except:
                    raise ValidationError("A system-error occurred when validating your XPath expression")

            if line.strip().startswith('xpath1:'):
                if not self.allow_xpath:
                    raise ValidationError("XPath not permitted in this field!")
                from lxml import etree, html
                tree = html.fromstring("<html></html>")
                line = re.sub(r'^xpath1:', '', line)

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
                if not self.allow_json:
                    raise ValidationError("jq not permitted in this field!")

            if 'jq:' in line:
                try:
                    import jq
                except ModuleNotFoundError:
                    # `jq` requires full compilation in windows and so isn't generally available
                    raise ValidationError("jq not support not found")

                input = line.replace('jq:', '')

                try:
                    jq.compile(input)
                except (ValueError) as e:
                    message = field.gettext('\'%s\' is not a valid jq expression. (%s)')
                    raise ValidationError(message % (input, str(e)))
                except:
                    raise ValidationError("A system-error occurred when validating your jq expression")

class ValidateSimpleURL:
    """Validate that the value can be parsed by urllib.parse.urlparse() and has a scheme/netloc."""
    def __init__(self, message=None):
        self.message = message or "Invalid URL."

    def __call__(self, form, field):
        data = (field.data or "").strip()
        if not data:
            return  # empty is OK — pair with validators.Optional()
        from urllib.parse import urlparse

        parsed = urlparse(data)
        if not parsed.scheme or not parsed.netloc:
            raise ValidationError(self.message)

class ValidateStartsWithRegex(object):
    def __init__(self, regex, *, flags=0, message=None, allow_empty=True, split_lines=True):
        # compile with given flags (we’ll pass re.IGNORECASE below)
        self.pattern = re.compile(regex, flags) if isinstance(regex, str) else regex
        self.message = message
        self.allow_empty = allow_empty
        self.split_lines = split_lines

    def __call__(self, form, field):
        data = field.data
        if not data:
            return

        # normalize into list of lines
        if isinstance(data, str) and self.split_lines:
            lines = data.splitlines()
        elif isinstance(data, (list, tuple)):
            lines = data
        else:
            lines = [data]

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if self.allow_empty:
                    continue
                raise ValidationError(self.message or _l("Empty value not allowed."))
            if not self.pattern.match(stripped):
                raise ValidationError(self.message or _l("Invalid value."))

class quickWatchForm(Form):
    url = fields.URLField(_l('URL'), validators=[validateURL()])
    tags = StringTagUUID(_l('Group tag'), validators=[validators.Optional()])
    watch_submit_button = SubmitField(_l('Watch'), render_kw={"class": "pure-button pure-button-primary"})
    processor = RadioField(_l('Processor'), choices=lambda: processors.available_processors(), default="text_json_diff")
    edit_and_watch_submit_button = SubmitField(_l('Edit > Watch'), render_kw={"class": "pure-button pure-button-primary"})


class QuickEventForm(Form):
    """Quick Event Entry Form for rapid event creation."""
    url = fields.URLField(_l('URL'), validators=[validateURL()])
    tags = StringTagUUID(_l('Tags'), validators=[validators.Optional()])
    auto_extract = BooleanField(_l('Auto-extract fields on first check'), default=True)
    event_name = StringField(_l('Event Name'), validators=[validators.Optional()])
    artist = StringField(_l('Artist'), validators=[validators.Optional(), validators.Length(max=500)])
    venue = StringField(_l('Venue'), validators=[validators.Optional(), validators.Length(max=500)])
    event_date = StringField(_l('Event Date'), validators=[validators.Optional(), validators.Length(max=100)])
    event_time = StringField(_l('Event Time'), validators=[validators.Optional(), validators.Length(max=100)])
    add_event_button = SubmitField(_l('Add Event'), render_kw={"class": "pure-button pure-button-primary"})
    add_and_open_settings = SubmitField(_l('Add & Open Settings'), render_kw={"class": "pure-button button-secondary"})


class EventFilterForm(Form):
    """Filter form for event list filtering and sorting (US-021)."""
    # Text search - searches event name and artist
    q = StringField(_l('Search'), validators=[validators.Optional()], render_kw={"placeholder": "Search by name or artist..."})

    # Tag filter - multiselect handled via multiple tag params in URL
    # Tags are handled separately in the template via checkboxes

    # Sold out status filter
    STOCK_STATUS_CHOICES = [
        ('all', _l('All')),
        ('available', _l('Available')),
        ('sold_out', _l('Sold Out')),
    ]
    stock_status = SelectField(_l('Stock Status'), choices=STOCK_STATUS_CHOICES, default='all')

    # Date range filters
    date_from = StringField(_l('From Date'), validators=[validators.Optional()], render_kw={"type": "date"})
    date_to = StringField(_l('To Date'), validators=[validators.Optional()], render_kw={"type": "date"})

    # Sort options
    SORT_CHOICES = [
        ('last_changed', _l('Last Changed')),
        ('last_checked', _l('Last Checked')),
        ('date_created', _l('Created Date')),
        ('event_date', _l('Event Date')),
        ('label', _l('Name')),
    ]
    sort = SelectField(_l('Sort By'), choices=SORT_CHOICES, default='last_changed')

    ORDER_CHOICES = [
        ('desc', _l('Newest First')),
        ('asc', _l('Oldest First')),
    ]
    order = SelectField(_l('Order'), choices=ORDER_CHOICES, default='desc')


# Common to a single watch and the global settings
class commonSettingsForm(Form):
    from . import processors

    def __init__(self, formdata=None, obj=None, prefix="", data=None, meta=None, **kwargs):
        super().__init__(formdata, obj, prefix, data, meta, **kwargs)
        self.notification_body.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})
        self.notification_title.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})
        self.notification_urls.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})

    fetch_backend = RadioField(_l('Fetch Method'), choices=content_fetchers.available_fetchers(), validators=[ValidateContentFetcherIsReady()])
    notification_body = TextAreaField(_l('Notification Body'), default='{{ watch_url }} had a change.', validators=[validators.Optional(), ValidateJinja2Template()])
    notification_format = SelectField(_l('Notification format'), choices=list(valid_notification_formats.items()))
    notification_title = StringField(_l('Notification Title'), default='ChangeDetection.io Notification - {{ watch_url }}', validators=[validators.Optional(), ValidateJinja2Template()])
    notification_urls = StringListField(_l('Notification URL List'), validators=[validators.Optional(), ValidateAppRiseServers(), ValidateJinja2Template()])
    processor = RadioField( label=_l("Processor - What do you want to achieve?"), choices=lambda: processors.available_processors(), default="text_json_diff")
    scheduler_timezone_default = StringField(_l("Default timezone for watch check scheduler"), render_kw={"list": "timezones"}, validators=[validateTimeZoneName()])
    webdriver_delay = IntegerField(_l('Wait seconds before extracting text'), validators=[validators.Optional(), validators.NumberRange(min=1, message=_l("Should contain one or more seconds"))])

# Not true anymore but keep the validate_ hook for future use, we convert color tags
#    def validate_notification_urls(self, field):
#        """Validate that HTML Color format is not used with Telegram"""
#        if self.notification_format.data == 'HTML Color' and field.data:
#            for url in field.data:
#                if url and ('tgram://' in url or 'discord://' in url or 'discord.com/api/webhooks' in url):
#                    raise ValidationError('HTML Color format is not supported by Telegram and Discord. Please choose another Notification Format (Plain Text, HTML, or Markdown to HTML).')


class importForm(Form):
    processor = RadioField(_l('Processor'), choices=lambda: processors.available_processors(), default="text_json_diff")
    urls = TextAreaField(_l('URLs'))
    xlsx_file = FileField(_l('Upload .xlsx file'), validators=[FileAllowed(['xlsx'], _l('Must be .xlsx file!'))])
    file_mapping = SelectField(_l('File mapping'), [validators.DataRequired()], choices={('wachete', 'Wachete mapping'), ('custom','Custom mapping')})

class SingleBrowserStep(Form):

    operation = SelectField(_l('Operation'), [validators.Optional()], choices=browser_step_ui_config.keys())

    # maybe better to set some <script>var..
    selector = StringField(_l('Selector'), [validators.Optional()], render_kw={"placeholder": "CSS or xPath selector"})
    optional_value = StringField(_l('value'), [validators.Optional()], render_kw={"placeholder": "Value"})
#   @todo move to JS? ajax fetch new field?
#    remove_button = SubmitField(_l('-'), render_kw={"type": "button", "class": "pure-button pure-button-primary", 'title': 'Remove'})
#    add_button = SubmitField(_l('+'), render_kw={"type": "button", "class": "pure-button pure-button-primary", 'title': 'Add new step after'})

class processor_text_json_diff_form(commonSettingsForm):

    url = fields.URLField('Web Page URL', validators=[validateURL()])
    tags = StringTagUUID('Group Tag', [validators.Optional()], default='')

    time_between_check = EnhancedFormField(
        TimeBetweenCheckForm,
        label=_l('Time Between Check'),
        conditional_field='time_between_check_use_default',
        conditional_message=REQUIRE_ATLEAST_ONE_TIME_PART_WHEN_NOT_GLOBAL_DEFAULT,
        conditional_test_function=validate_time_between_check_has_values
    )

    time_schedule_limit = FormField(ScheduleLimitForm)

    time_between_check_use_default = BooleanField(_l('Use global settings for time between check and scheduler.'), default=False)

    include_filters = StringListField(_l('CSS/JSONPath/JQ/XPath Filters'), [ValidateCSSJSONXPATHInput()], default='')

    subtractive_selectors = StringListField(_l('Remove elements'), [ValidateCSSJSONXPATHInput(allow_json=False)])

    extract_text = StringListField(_l('Extract text'), [ValidateListRegex()])

    title = StringField(_l('Title'), default='')

    ignore_text = StringListField(_l('Ignore lines containing'), [ValidateListRegex()])
    headers = StringDictKeyValue('Request headers')
    body = TextAreaField(_l('Request body'), [validators.Optional()])
    method = SelectField(_l('Request method'), choices=valid_method, default=default_method)
    ignore_status_codes = BooleanField(_l('Ignore status codes (process non-2xx status codes as normal)'), default=False)
    check_unique_lines = BooleanField(_l('Only trigger when unique lines appear in all history'), default=False)
    remove_duplicate_lines = BooleanField(_l('Remove duplicate lines of text'), default=False)
    sort_text_alphabetically =  BooleanField(_l('Sort text alphabetically'), default=False)
    strip_ignored_lines = TernaryNoneBooleanField(_l('Strip ignored lines'), default=None)
    trim_text_whitespace = BooleanField(_l('Trim whitespace before and after text'), default=False)

    filter_text_added = BooleanField(_l('Added lines'), default=True)
    filter_text_replaced = BooleanField(_l('Replaced/changed lines'), default=True)
    filter_text_removed = BooleanField(_l('Removed lines'), default=True)

    trigger_text = StringListField(_l('Keyword triggers - Trigger/wait for text'), [validators.Optional(), ValidateListRegex()])
    if os.getenv("PLAYWRIGHT_DRIVER_URL"):
        browser_steps = FieldList(FormField(SingleBrowserStep), min_entries=10)
    text_should_not_be_present = StringListField(_l('Block change-detection while text matches'), [validators.Optional(), ValidateListRegex()])

    # Watch words - simplified text matching for restock/sold-out alerts
    block_words = StringListField(
        _l('Notify when DISAPPEARS'),
        [validators.Optional(), ValidateListRegex()],
        render_kw={"placeholder": "Sold Out\nNot Available\nOff Sale"}
    )
    trigger_words = StringListField(
        _l('Notify when APPEARS'),
        [validators.Optional(), ValidateListRegex()],
        render_kw={"placeholder": "Tickets Available\nOn Sale Now"}
    )

    # Event metadata
    artist = StringField(_l('Artist'), [validators.Optional(), validators.Length(max=500)])
    venue = StringField(_l('Venue'), [validators.Optional(), validators.Length(max=500)])
    event_date = StringField(_l('Event Date'), [validators.Optional(), validators.Length(max=100)], render_kw={"placeholder": "Jan 15, 2026"})

    webdriver_js_execute_code = TextAreaField(_l('Execute JavaScript before change detection'), render_kw={"rows": "5"}, validators=[validators.Optional()])

    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})

    proxy = RadioField(_l('Proxy'))
    # filter_failure_notification_send @todo make ternary
    filter_failure_notification_send = BooleanField(_l('Send a notification when the filter can no longer be found on the page'), default=False)
    notification_muted = TernaryNoneBooleanField(_l('Notifications'), default=None, yes_text=_l("Muted"), no_text=_l("On"))
    notification_screenshot = BooleanField(_l('Attach screenshot to notification (where possible)'), default=False)

    conditions_match_logic = RadioField(_l('Match'), choices=[('ALL', _l('Match all of the following')),('ANY', _l('Match any of the following'))], default='ALL')
    conditions = FieldList(FormField(ConditionFormRow), min_entries=1)  # Add rule logic here
    use_page_title_in_list = TernaryNoneBooleanField(_l('Use page <title> in list'), default=None)

    def extra_tab_content(self):
        return None

    def extra_form_content(self):
        return None

    def validate(self, **kwargs):
        if not super().validate():
            return False

        from changedetectionio.jinja2_custom import render as jinja_render
        result = True

        # Fail form validation when a body is set for a GET
        if self.method.data == 'GET' and self.body.data:
            self.body.errors.append(gettext('Body must be empty when Request Method is set to GET'))
            result = False

        # Attempt to validate jinja2 templates in the URL
        try:
            jinja_render(template_str=self.url.data)
        except ModuleNotFoundError as e:
            # incase jinja2_time or others is missing
            logger.error(e)
            self.url.errors.append(gettext('Invalid template syntax configuration: %(error)s') % {'error': e})
            result = False
        except Exception as e:
            logger.error(e)
            self.url.errors.append(gettext('Invalid template syntax: %(error)s') % {'error': e})
            result = False

        # Attempt to validate jinja2 templates in the body
        if self.body.data and self.body.data.strip():
            try:
                jinja_render(template_str=self.body.data)
            except ModuleNotFoundError as e:
                # incase jinja2_time or others is missing
                logger.error(e)
                self.body.errors.append(gettext('Invalid template syntax configuration: %(error)s') % {'error': e})
                result = False
            except Exception as e:
                logger.error(e)
                self.body.errors.append(gettext('Invalid template syntax: %(error)s') % {'error': e})
                result = False

        # Attempt to validate jinja2 templates in the headers
        if len(self.headers.data) > 0:
            try:
                for header, value in self.headers.data.items():
                    jinja_render(template_str=value)
            except ModuleNotFoundError as e:
                # incase jinja2_time or others is missing
                logger.error(e)
                self.headers.errors.append(gettext('Invalid template syntax configuration: %(error)s') % {'error': e})
                result = False
            except Exception as e:
                logger.error(e)
                self.headers.errors.append(gettext('Invalid template syntax in \"%(header)s\" header: %(error)s') % {'header': header, 'error': e})
                result = False

        return result

    def __init__(
            self,
            formdata=None,
            obj=None,
            prefix="",
            data=None,
            meta=None,
            **kwargs,
    ):
        super().__init__(formdata, obj, prefix, data, meta, **kwargs)
        if kwargs and kwargs.get('default_system_settings'):
            default_tz = kwargs.get('default_system_settings').get('application', {}).get('scheduler_timezone_default')
            if default_tz:
                self.time_schedule_limit.form.timezone.render_kw['placeholder'] = default_tz



class SingleExtraProxy(Form):
    # maybe better to set some <script>var..
    proxy_name = StringField(_l('Name'), [validators.Optional()], render_kw={"placeholder": "Name"})
    proxy_url = StringField(_l('Proxy URL'), [
        validators.Optional(),
        ValidateStartsWithRegex(
            regex=r'^(https?|socks5)://',  # ✅ main pattern
            flags=re.IGNORECASE,  # ✅ makes it case-insensitive
            message=_l('Proxy URLs must start with http://, https:// or socks5://'),
        ),
        ValidateSimpleURL()
    ], render_kw={"placeholder": "socks5:// or regular proxy http://user:pass@...:3128", "size":50})

class SingleExtraBrowser(Form):
    browser_name = StringField(_l('Name'), [validators.Optional()], render_kw={"placeholder": "Name"})
    browser_connection_url = StringField(_l('Browser connection URL'), [
        validators.Optional(),
        ValidateStartsWithRegex(
            regex=r'^(wss?|ws)://',
            flags=re.IGNORECASE,
            message=_l('Browser URLs must start with wss:// or ws://')
        ),
        ValidateSimpleURL()
    ], render_kw={"placeholder": "wss://brightdata... wss://oxylabs etc", "size":50})

class DefaultUAInputForm(Form):
    html_requests = StringField(_l('Plaintext requests'), validators=[validators.Optional()], render_kw={"placeholder": "<default>"})
    if os.getenv("PLAYWRIGHT_DRIVER_URL") or os.getenv("WEBDRIVER_URL"):
        html_webdriver = StringField(_l('Chrome requests'), validators=[validators.Optional()], render_kw={"placeholder": "<default>"})

# datastore.data['settings']['requests']..
class globalSettingsRequestForm(Form):
    time_between_check = RequiredFormField(TimeBetweenCheckForm, label=_l('Time Between Check'))
    time_schedule_limit = FormField(ScheduleLimitForm)
    proxy = RadioField(_l('Default proxy'))
    jitter_seconds = IntegerField(_l('Random jitter seconds ± check'),
                                  render_kw={"style": "width: 5em;"},
                                  validators=[validators.NumberRange(min=0, message=_l("Should contain zero or more seconds"))])
    
    workers = IntegerField(_l('Number of fetch workers'),
                          render_kw={"style": "width: 5em;"},
                          validators=[validators.NumberRange(min=1, max=50,
                                                             message=_l("Should be between 1 and 50"))])

    timeout = IntegerField(_l('Requests timeout in seconds'),
                           render_kw={"style": "width: 5em;"},
                           validators=[validators.NumberRange(min=1, max=999,
                                                              message=_l("Should be between 1 and 999"))])

    extra_proxies = FieldList(FormField(SingleExtraProxy), min_entries=5)
    extra_browsers = FieldList(FormField(SingleExtraBrowser), min_entries=5)

    default_ua = FormField(DefaultUAInputForm, label=_l("Default User-Agent overrides"))

    def validate_extra_proxies(self, extra_validators=None):
        for e in self.data['extra_proxies']:
            if e.get('proxy_name') or e.get('proxy_url'):
                if not e.get('proxy_name','').strip() or not e.get('proxy_url','').strip():
                    self.extra_proxies.errors.append(gettext('Both a name, and a Proxy URL is required.'))
                    return False

class globalSettingsApplicationUIForm(Form):
    open_diff_in_new_tab = BooleanField(_l("Open 'History' page in a new tab"), default=True, validators=[validators.Optional()])
    socket_io_enabled = BooleanField(_l('Realtime UI Updates Enabled'), default=True, validators=[validators.Optional()])
    favicons_enabled = BooleanField(_l('Favicons Enabled'), default=True, validators=[validators.Optional()])
    use_page_title_in_list = BooleanField(_l('Use page <title> in watch overview list')) #BooleanField=True


class LLMExtractionForm(Form):
    """Form for LLM extraction settings (US-026)."""
    enabled = BooleanField(_l('Enable AI Extraction'), default=False, validators=[validators.Optional()])
    provider = SelectField(
        _l('Provider'),
        choices=[
            ('', _l('-- Select Provider --')),
            ('openai', 'OpenAI'),
            ('anthropic', 'Anthropic'),
            ('ollama', 'Ollama (Local)'),
        ],
        default='',
        validators=[validators.Optional()]
    )
    api_key = StringField(
        _l('API Key'),
        validators=[validators.Optional()],
        render_kw={"type": "password", "placeholder": "Enter API key...", "autocomplete": "new-password"}
    )
    model = SelectField(
        _l('Model'),
        choices=[('', _l('-- Select Provider First --'))],
        default='',
        validators=[validators.Optional()]
    )
    api_base_url = StringField(
        _l('Custom API URL'),
        validators=[validators.Optional()],
        render_kw={"placeholder": "Optional: Custom API endpoint URL"}
    )
    prompt_template = TextAreaField(
        _l('Custom Extraction Prompt'),
        validators=[validators.Optional()],
        render_kw={"rows": "8", "placeholder": "Leave empty to use default prompt..."}
    )
    timeout = IntegerField(
        _l('Request Timeout (seconds)'),
        default=30,
        validators=[validators.Optional(), validators.NumberRange(min=5, max=300, message=_l("Should be between 5 and 300 seconds"))]
    )
    fallback_to_css = BooleanField(_l('Fall back to CSS selectors if AI extraction fails'), default=True, validators=[validators.Optional()])
    max_html_chars = IntegerField(
        _l('Maximum HTML Characters'),
        default=50000,
        validators=[validators.Optional(), validators.NumberRange(min=1000, max=200000, message=_l("Should be between 1000 and 200000"))]
    )

# datastore.data['settings']['application']..
class globalSettingsApplicationForm(commonSettingsForm):

    api_access_token_enabled = BooleanField(_l('API access token security check enabled'), default=True, validators=[validators.Optional()])
    base_url = StringField(_l('Notification base URL override'),
                           validators=[validators.Optional()],
                           render_kw={"placeholder": os.getenv('BASE_URL', 'Not set')}
                           )
    empty_pages_are_a_change =  BooleanField(_l('Treat empty pages as a change?'), default=False)
    fetch_backend = RadioField(_l('Fetch Method'), default="html_requests", choices=content_fetchers.available_fetchers(), validators=[ValidateContentFetcherIsReady()])
    global_ignore_text = StringListField(_l('Ignore Text'), [ValidateListRegex()])
    global_subtractive_selectors = StringListField(_l('Remove elements'), [ValidateCSSJSONXPATHInput(allow_json=False)])
    ignore_whitespace = BooleanField(_l('Ignore whitespace'))

    # Screenshot comparison settings
    min_change_percentage = FloatField(
        'Screenshot: Minimum Change Percentage',
        validators=[
            validators.Optional(),
            validators.NumberRange(min=0.0, max=100.0, message=_l('Must be between 0 and 100'))
        ],
        default=0.1,
        render_kw={"placeholder": "0.1", "style": "width: 8em;"}
    )

    password = SaltyPasswordField(_l('Password'))
    pager_size = IntegerField(_l('Pager size'),
                              render_kw={"style": "width: 5em;"},
                              validators=[validators.NumberRange(min=0,
                                                                 message=_l("Should be atleast zero (disabled)"))])

    rss_content_format = SelectField(_l('RSS Content format'), choices=list(RSS_FORMAT_TYPES.items()))
    rss_template_type = SelectField(_l('RSS <description> body built from'), choices=list(RSS_TEMPLATE_TYPE_OPTIONS.items()))
    rss_template_override = TextAreaField(_l('RSS "System default" template override'), render_kw={"rows": "5", "placeholder": RSS_TEMPLATE_HTML_DEFAULT}, validators=[validators.Optional(), ValidateJinja2Template()])

    removepassword_button = SubmitField(_l('Remove password'), render_kw={"class": "pure-button pure-button-primary"})
    render_anchor_tag_content = BooleanField(_l('Render anchor tag content'), default=False)
    shared_diff_access = BooleanField(_l('Allow anonymous access to watch history page when password is enabled'), default=False, validators=[validators.Optional()])
    strip_ignored_lines = BooleanField(_l('Strip ignored lines'))
    rss_hide_muted_watches = BooleanField(_l('Hide muted watches from RSS feed'), default=True,
                                      validators=[validators.Optional()])

    rss_reader_mode = BooleanField(_l('Enable RSS reader mode '), default=False, validators=[validators.Optional()])
    rss_diff_length = IntegerField(label=_l('Number of changes to show in watch RSS feed'),
                                   render_kw={"style": "width: 5em;"},
                                   validators=[validators.NumberRange(min=0, message=_l("Should contain zero or more attempts"))])

    filter_failure_notification_threshold_attempts = IntegerField(_l('Number of times the filter can be missing before sending a notification'),
                                                                  render_kw={"style": "width: 5em;"},
                                                                  validators=[validators.NumberRange(min=0,
                                                                                                     message=_l("Should contain zero or more attempts"))])
    ui = FormField(globalSettingsApplicationUIForm)

    # LLM Extraction settings (US-026)
    llm_extraction = FormField(LLMExtractionForm)


class globalSettingsForm(Form):
    # Define these as FormFields/"sub forms", this way it matches the JSON storage
    # datastore.data['settings']['application']..
    # datastore.data['settings']['requests']..
    def __init__(self, formdata=None, obj=None, prefix="", data=None, meta=None, **kwargs):
        super().__init__(formdata, obj, prefix, data, meta, **kwargs)
        self.application.notification_body.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})
        self.application.notification_title.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})
        self.application.notification_urls.extra_notification_tokens = kwargs.get('extra_notification_tokens', {})

    requests = FormField(globalSettingsRequestForm)
    application = FormField(globalSettingsApplicationForm)
    save_button = SubmitField(_l('Save'), render_kw={"class": "pure-button pure-button-primary"})


class extractDataForm(Form):
    extract_regex = StringField(_l('RegEx to extract'), validators=[validators.DataRequired(), ValidateSinglePythonRegexString()])
    extract_submit_button = SubmitField(_l('Extract as CSV'), render_kw={"class": "pure-button pure-button-primary"})
