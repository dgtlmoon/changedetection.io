from wtforms import (
    BooleanField,
    validators,
    FloatField
)
from wtforms.fields.choices import RadioField
from wtforms.fields.form import FormField
from wtforms.form import Form
from flask_babel import lazy_gettext as _l

from changedetectionio.forms import processor_text_json_diff_form


class RestockSettingsForm(Form):
    in_stock_processing = RadioField(label=_l('Re-stock detection'), choices=[
        ('in_stock_only', _l("In Stock only (Out Of Stock -> In Stock only)")),
        ('all_changes', _l("Any availability changes")),
        ('off', _l("Off, don't follow availability/restock")),
    ], default="in_stock_only")

    price_change_min = FloatField(_l('Below price to trigger notification'), [validators.Optional()],
                                  render_kw={"placeholder": _l("No limit"), "size": "10"})
    price_change_max = FloatField(_l('Above price to trigger notification'), [validators.Optional()],
                                  render_kw={"placeholder": _l("No limit"), "size": "10"})
    price_change_threshold_percent = FloatField(_l('Threshold (%) for price changes since the previous check'), validators=[

        validators.Optional(),
        validators.NumberRange(min=0, max=100, message=_l("Should be between 0 and 100")),
    ], render_kw={"placeholder": "0%", "size": "5"})

    follow_price_changes = BooleanField(_l('Follow price changes'), default=True)

class processor_settings_form(processor_text_json_diff_form):
    processor_config_restock_diff = FormField(RestockSettingsForm)

    def extra_tab_content(self):
        return _l('Restock & Price Detection')

    def extra_form_template(self):
        # Rendered with Flask's render_template() so the help text is extracted for translation (#4612)
        return 'restock_diff/edit-extras.html'

    def tag_overrides_restock(self):
        """True when one of this watch's group tags overrides its restock/price settings."""
        if getattr(self, 'watch', None) and getattr(self, 'datastore', None):
            tags = self.datastore.data['settings']['application']['tags']
            return any(tags.get(tag_uuid, {}).get('overrides_watch') for tag_uuid in self.watch.get('tags', []))
        return False
