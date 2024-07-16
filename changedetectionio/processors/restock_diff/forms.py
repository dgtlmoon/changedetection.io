from wtforms import (
    BooleanField,
    validators,
    FloatField
)
from wtforms.fields.choices import RadioField
from wtforms.fields.form import FormField
from wtforms.form import Form

from changedetectionio.forms import processor_text_json_diff_form


class RestockSettingsForm(Form):
    in_stock_processing = RadioField(label='Re-stock detection', choices=[
        ('in_stock_only', "In Stock only (Out Of Stock -> In Stock only)"),
        ('all_changes', "Any availability changes"),
        ('off', "Off, don't follow availability/restock"),
    ], default="in_stock_only")

    price_change_min = FloatField('Below price to trigger notification', [validators.Optional()],
                                  render_kw={"placeholder": "No limit", "size": "10"})
    price_change_max = FloatField('Above price to trigger notification', [validators.Optional()],
                                  render_kw={"placeholder": "No limit", "size": "10"})
    price_change_threshold_percent = FloatField('Threshold in % for price changes since the original price', validators=[

        validators.Optional(),
        validators.NumberRange(min=0, max=100, message="Should be between 0 and 100"),
    ], render_kw={"placeholder": "0%", "size": "5"})

    follow_price_changes = BooleanField('Follow price changes', default=True)

class processor_settings_form(processor_text_json_diff_form):
    restock_settings = FormField(RestockSettingsForm)

    def extra_tab_content(self):
        return 'Restock & Price Detection'

    def extra_form_content(self):
        output = ""

        if getattr(self, 'watch', None) and getattr(self, 'datastore'):
            for tag_uuid in self.watch.get('tags'):
                tag = self.datastore.data['settings']['application']['tags'].get(tag_uuid, {})
                if tag.get('overrides_watch'):
                    # @todo - Quick and dirty, cant access 'url_for' here because its out of scope somehow
                    output = f"""<p><strong>Note! A Group tag overrides the restock and price detection here.</strong></p><style>#restock-fieldset-price-group {{ opacity: 0.6; }}</style>"""

        output += """
        {% from '_helpers.html' import render_field, render_checkbox_field, render_button %}
        <script>        
            $(document).ready(function () {
                toggleOpacity('#restock_settings-follow_price_changes', '.price-change-minmax', true);
            });
        </script>

        <fieldset id="restock-fieldset-price-group">
            <div class="pure-control-group">
                <fieldset class="pure-group inline-radio">
                    {{ render_field(form.restock_settings.in_stock_processing) }}
                </fieldset>
                <fieldset class="pure-group">
                    {{ render_checkbox_field(form.restock_settings.follow_price_changes) }}
                    <span class="pure-form-message-inline">Changes in price should trigger a notification</span>
                </fieldset>
                <fieldset class="pure-group price-change-minmax">               
                    {{ render_field(form.restock_settings.price_change_min, placeholder=watch.get('restock', {}).get('price')) }}
                    <span class="pure-form-message-inline">Minimum amount, Trigger a change/notification when the price drops <i>below</i> this value.</span>
                </fieldset>
                <fieldset class="pure-group price-change-minmax">
                    {{ render_field(form.restock_settings.price_change_max, placeholder=watch.get('restock', {}).get('price')) }}
                    <span class="pure-form-message-inline">Maximum amount, Trigger a change/notification when the price rises <i>above</i> this value.</span>
                </fieldset>
                <fieldset class="pure-group price-change-minmax">
                    {{ render_field(form.restock_settings.price_change_threshold_percent) }}
                    <span class="pure-form-message-inline">Price must change more than this % to trigger a change since the first check.</span><br>
                    <span class="pure-form-message-inline">For example, If the product is $1,000 USD originally, <strong>2%</strong> would mean it has to change more than $20 since the first check.</span><br>
                </fieldset>                
            </div>
        </fieldset>
        """
        return output