
from wtforms import (
    BooleanField,
    validators,
    FloatField
)

from changedetectionio.forms import processor_text_json_diff_form

class processor_settings_form(processor_text_json_diff_form):
    in_stock_only = BooleanField('Only trigger when product goes BACK to in-stock', default=True)
    price_change_min = FloatField('Minimum amount to trigger notification', [validators.Optional()],
                                  render_kw={"placeholder": "No limit", "size": "10"})
    price_change_max = FloatField('Maximum amount to trigger notification', [validators.Optional()],
                                  render_kw={"placeholder": "No limit", "size": "10"})
    price_change_threshold_percent = FloatField('Threshold in % for price changes since the original price', validators=[

        validators.Optional(),
        validators.NumberRange(min=0, max=100, message="Should be between 0 and 100"),
    ], render_kw={"placeholder": "0%", "size": "5"})

    follow_price_changes = BooleanField('Follow price changes', default=False)

    def extra_tab_content(self):
        return 'Restock & Price Detection'

    def extra_form_content(self):
        return """
        {% from '_helpers.html' import render_field, render_checkbox_field, render_button %}
        <script>        
            $(document).ready(function () {
                toggleOpacity('#follow_price_changes', '.price-change-minmax', true);
            });
        </script>


        <fieldset>
            <div class="pure-control-group">
                <fieldset class="pure-group">
                    {{ render_checkbox_field(form.in_stock_only) }}
                    <span class="pure-form-message-inline">Only trigger re-stock notification when page changes from <strong>out of stock</strong> to <strong>back in stock</strong></span>
                </fieldset>
                <fieldset class="pure-group">
                    {{ render_checkbox_field(form.follow_price_changes) }}
                    <span class="pure-form-message-inline">Changes in price should trigger a notification</span>
                    <br>
                    <span class="pure-form-message-inline">When OFF - Only care about restock detection</span>                    
                </fieldset>
                <fieldset class="pure-group price-change-minmax">               
                    {{ render_field(form.price_change_min, placeholder=watch['restock']['price']) }}
                    <span class="pure-form-message-inline">Minimum amount, only trigger a change when the price is less than this amount.</span>
                </fieldset>
                <fieldset class="pure-group price-change-minmax">
                    {{ render_field(form.price_change_max, placeholder=watch['restock']['price']) }}
                    <span class="pure-form-message-inline">Maximum amount, only trigger a change when the price is more than this amount.</span>
                </fieldset>
                <fieldset class="pure-group price-change-minmax">
                    {{ render_field(form.price_change_threshold_percent) }}
                    <span class="pure-form-message-inline">Price must change more than this % to trigger a change.</span><br>
                    <span class="pure-form-message-inline">For example, If the product is $1,000 USD originally, <strong>2%</strong> would mean it has to change more than $20 since the first check.</span><br>
                </fieldset>                
            </div>
        </fieldset>"""