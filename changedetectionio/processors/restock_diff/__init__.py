
from babel.numbers import parse_decimal
from changedetectionio.model.Watch import model as BaseWatch
from typing import Union
import re

class Restock(dict):

    def parse_currency(self, raw_value: str) -> Union[float, None]:
        # Clean and standardize the value (ie 1,400.00 should be 1400.00), even better would be store the whole thing as an integer.
        standardized_value = raw_value

        if ',' in standardized_value and '.' in standardized_value:
            # Identify the correct decimal separator
            if standardized_value.rfind('.') > standardized_value.rfind(','):
                standardized_value = standardized_value.replace(',', '')
            else:
                standardized_value = standardized_value.replace('.', '').replace(',', '.')
        else:
            standardized_value = standardized_value.replace(',', '.')

        # Remove any non-numeric characters except for the decimal point
        standardized_value = re.sub(r'[^\d.-]', '', standardized_value)

        if standardized_value:
            # Convert to float
            return float(parse_decimal(standardized_value, locale='en'))

        return None

    def __init__(self, *args, **kwargs):
        # Define default values
        default_values = {
            'in_stock': None,
            'price': None,
            'currency': None,
            'original_price': None
        }

        # Initialize the dictionary with default values
        super().__init__(default_values)

        # Update with any provided positional arguments (dictionaries)
        if args:
            if len(args) == 1 and isinstance(args[0], dict):
                self.update(args[0])
            else:
                raise ValueError("Only one positional argument of type 'dict' is allowed")

    def __setitem__(self, key, value):
        # Custom logic to handle setting price and original_price
        if key == 'price' or key == 'original_price':
            if isinstance(value, str):
                value = self.parse_currency(raw_value=value)

        super().__setitem__(key, value)

class Watch(BaseWatch):
    def __init__(self, *arg, **kw):
        super().__init__(*arg, **kw)
        self['restock'] = Restock(kw['default']['restock']) if kw.get('default') and kw['default'].get('restock') else Restock()

        self['restock_settings'] = kw['default']['restock_settings'] if kw.get('default',{}).get('restock_settings') else {
            'follow_price_changes': True,
            'in_stock_processing' : 'in_stock_only'
        } #@todo update

    def clear_watch(self):
        super().clear_watch()
        self.update({'restock': Restock()})

    def extra_notification_token_values(self):
        values = super().extra_notification_token_values()
        values['restock'] = self.get('restock', {})
        return values

    def extra_notification_token_placeholder_info(self):
        values = super().extra_notification_token_placeholder_info()

        values.append(('restock.price', "Price detected"))
        values.append(('restock.original_price', "Original price at first check"))

        return values

