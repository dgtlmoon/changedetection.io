"""
WTForms for the Browsers blueprint (browser configs / profiles).

Kept out of the top-level forms.py (which is already large). The field names match the
FetcherConfig pydantic model exactly, so the blueprint can map form -> FetcherConfig with a
plain dict comprehension. Value validation for locale/timezone lives in the pydantic model
(single source of truth); this form only enforces the UI-level rules (label required, types).
"""
from flask_babel import lazy_gettext as _l
from wtforms import (
    BooleanField,
    FloatField,
    Form,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    validators,
    widgets,
)

from changedetectionio import content_fetchers
from changedetectionio.forms import StringListField

# Playwright/puppeteer request.resource_type values worth blocking to save proxy bandwidth.
BLOCKABLE_RESOURCE_TYPES = [
    ('image', _l('Images')),
    ('font', _l('Fonts')),
    ('media', _l('Media (audio/video)')),
    ('stylesheet', _l('Stylesheets (CSS)')),
    ('script', _l('Scripts (JS)')),
    ('xhr', _l('XHR / fetch')),
    ('websocket', _l('WebSockets')),
]


def device_choices():
    """Grouped choices (WTForms renders a dict as <optgroup>s): desktop with its own size first,
    then phones and tablets. Device names are product names and aren't translated."""
    from changedetectionio.model.browser_devices import DEVICE_PRESETS
    def of(category):
        return [(name, name) for name, preset in DEVICE_PRESETS.items() if preset['category'] == category]
    return {
        _l('Desktop'): [('', _l('Desktop / custom size'))],
        _l('Phones'): of('phone'),
        _l('Tablets'): of('tablet'),
    }


class MultiCheckboxField(SelectMultipleField):
    """Render a SelectMultipleField as a list of checkboxes."""
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class BrowserOptionsForm(Form):
    # Human name shown in the list - REQUIRED, this is the label a watch selects by.
    label = StringField(_l('Name'), validators=[
        validators.DataRequired(message=_l("Give this browser config a name")),
        validators.Length(min=1, max=120),
    ], render_kw={"placeholder": _l("e.g. Desktop Full-HD, Mobile de-DE")})

    # --- FetcherConfig fields (names match the pydantic model) ---
    device = SelectField(_l('Emulate device'), choices=device_choices, default='',
                         validators=[validators.Optional()])
    device_scale_factor = FloatField(_l('Pixel density'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=3)],
        render_kw={"placeholder": "1", "step": "0.5", "style": "width: 6em;"})
    viewport_width = IntegerField(_l('Viewport width'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=10000)])
    viewport_height = IntegerField(_l('Viewport height'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=10000)])

    locale = StringField(_l('Locale'), validators=[validators.Optional(), validators.Length(max=35)],
                         render_kw={"placeholder": "de-DE", "list": "locale-datalist", "autocomplete": "off"})
    timezone_id = StringField(_l('Timezone'), validators=[validators.Optional(), validators.Length(max=64)],
                              render_kw={"placeholder": "Europe/Berlin", "list": "timezone-datalist", "autocomplete": "off"})

    # Local-launch engines only (gated by supports_browser_type)
    browser_type = SelectField(_l('Browser engine'), validators=[validators.Optional()],
                               choices=[('chromium', 'Chromium'), ('firefox', 'Firefox'), ('webkit', 'WebKit')],
                               default='chromium')
    delete_created_files = BooleanField(_l('Delete temporary browser files after each check'), default=True)

    block_resource_types = MultiCheckboxField(_l('Block asset types'), choices=BLOCKABLE_RESOURCE_TYPES)
    block_url_patterns = StringListField(_l('Block URL patterns'), validators=[validators.Optional()],
                                         render_kw={"placeholder": "*.ttf\n*/analytics/*"})

    # External browser endpoint (gated by supports_connection_url). No scheme/format validators
    # here on purpose: FetcherConfig.connection_url enforces them, and the blueprint attaches the
    # model's error to this field - so there is one rule, not a form copy that can drift.
    connection_url = StringField(_l('Browser connection URL'), validators=[validators.Optional()],
                                 render_kw={"placeholder": "wss://brd… wss://oxylabs… ws://my-browser:3000",
                                            "size": 50})

    # Plain HTTP client options (gated by supports_request_timeout / supports_custom_user_agent)
    timeout = IntegerField(_l('Request timeout (seconds)'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=999)],
        render_kw={"placeholder": "30", "style": "width: 6em;"})
    user_agent = StringField(_l('User-Agent'), validators=[validators.Optional(), validators.Length(max=500)],
                             render_kw={"placeholder": "Mozilla/5.0 (…)"})

    save = SubmitField(_l('Save'))

    @staticmethod
    def device_summaries():
        """{device name: 'width × height'} for the form script, which shows the device's screen
        size in the (disabled) viewport fields when a device is picked."""
        from changedetectionio.model.browser_devices import DEVICE_PRESETS
        return {name: preset['viewport'] for name, preset in DEVICE_PRESETS.items()}

    def to_fetcher_config_dict(self):
        """Map the FetcherConfig-named fields to a plain dict for FetcherConfig(**...)."""
        data = {
            'device': (self.device.data or None),
            'device_scale_factor': self.device_scale_factor.data,
            'viewport_width': self.viewport_width.data,
            'viewport_height': self.viewport_height.data,
            'locale': (self.locale.data or None),
            'timezone_id': (self.timezone_id.data or None),
            'browser_type': (self.browser_type.data or None),
            'delete_created_files': bool(self.delete_created_files.data),
            'block_resource_types': self.block_resource_types.data or [],
            'block_url_patterns': self.block_url_patterns.data or [],
            'connection_url': (self.connection_url.data or None),
            'user_agent': (self.user_agent.data or None),
        }
        # A device sets the screen size, so don't keep a viewport that would only sit there hidden
        if data['device']:
            data['viewport_width'] = None
            data['viewport_height'] = None
        else:
            data['device_scale_factor'] = None
        # Blank timeout means "use the model default" (DEFAULT_REQUEST_TIMEOUT_SECONDS), so omit the
        # key entirely rather than passing None (which would override that default).
        if self.timeout.data is not None:
            data['timeout'] = self.timeout.data
        return data
