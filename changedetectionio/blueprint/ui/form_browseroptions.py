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

SCREENSHOT_FORMATS = [('JPEG', 'JPEG'), ('PNG', 'PNG')]


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
    viewport_width = IntegerField(_l('Viewport width'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=10000)])
    viewport_height = IntegerField(_l('Viewport height'), validators=[
        validators.Optional(), validators.NumberRange(min=1, max=10000)])

    locale = StringField(_l('Locale'), validators=[validators.Optional(), validators.Length(max=35)],
                         render_kw={"placeholder": "de-DE", "list": "locale-datalist", "autocomplete": "off"})
    timezone_id = StringField(_l('Timezone'), validators=[validators.Optional(), validators.Length(max=64)],
                              render_kw={"placeholder": "Europe/Berlin", "list": "timezone-datalist", "autocomplete": "off"})

    screenshot_format = SelectField(_l('Screenshot format'), choices=SCREENSHOT_FORMATS, default='JPEG')

    # Local-launch engines only (gated by supports_browser_type)
    browser_type = SelectField(_l('Browser engine'), validators=[validators.Optional()],
                               choices=[('chromium', 'Chromium'), ('firefox', 'Firefox'), ('webkit', 'WebKit')],
                               default='chromium')
    delete_created_files = BooleanField(_l('Delete temporary browser files after each check'), default=True)

    block_resource_types = MultiCheckboxField(_l('Block asset types'), choices=BLOCKABLE_RESOURCE_TYPES)
    block_url_patterns = StringListField(_l('Block URL patterns'), validators=[validators.Optional()],
                                         render_kw={"placeholder": "*.ttf\n*/analytics/*"})

    save = SubmitField(_l('Save'))

    def to_fetcher_config_dict(self):
        """Map the FetcherConfig-named fields to a plain dict for FetcherConfig(**...)."""
        return {
            'viewport_width': self.viewport_width.data,
            'viewport_height': self.viewport_height.data,
            'locale': (self.locale.data or None),
            'timezone_id': (self.timezone_id.data or None),
            'screenshot_format': self.screenshot_format.data,
            'browser_type': (self.browser_type.data or None),
            'delete_created_files': bool(self.delete_created_files.data),
            'block_resource_types': self.block_resource_types.data or [],
            'block_url_patterns': self.block_url_patterns.data or [],
        }
