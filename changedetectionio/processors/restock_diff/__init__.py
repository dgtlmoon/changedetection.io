
from babel.numbers import parse_decimal
from changedetectionio.model.Watch import model as BaseWatch
from decimal import Decimal, InvalidOperation
from typing import Union
import re

# Processor capabilities
supports_visual_selector = True
supports_browser_steps = True
supports_text_filters_and_triggers = True
supports_text_filters_and_triggers_elements = True
supports_request_type = True
_price_re = re.compile(r"Price:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


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
            # @todo locale needs to be the locale of the webpage
            return float(parse_decimal(standardized_value, locale='en'))

        return None

    def __init__(self, *args, **kwargs):
        # Define default values
        default_values = {
            'in_stock': None,
            'price': None,
            'currency': None,
            'original_price': None,
            'prev_price': None  # price at the previous check, for the watch-list up/down arrow (display only)
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

    def get_prev_price(self):
        """Price at the previous check. Falls back to original_price for watches
        saved before prev_price existed. Returns a float or None."""
        prev = self.get('prev_price')
        if prev is None:
            prev = self.get('original_price')
        return prev

    def get_price_change_percent(self):
        """Signed % change of the current price vs the previous price, rounded to one
        decimal place (e.g. -18.0, 5.3). Returns None when it can't be computed -
        no/zero previous price, non-numeric values, or no change."""
        try:
            price = float(self.get('price'))
            prev = self.get_prev_price()
            prev = float(prev) if prev is not None else None
        except (TypeError, ValueError):
            return None

        if prev is None or prev == 0:
            return None

        pct = round((price - prev) / prev * 100.0, 1)
        return pct if pct != 0 else None

def get_price_from_history_str(history_str):
    m = _price_re.search(history_str)
    if not m:
        return None

    try:
        return str(Decimal(m.group(1)))
    except InvalidOperation:
        return None


class Watch(BaseWatch):
    def __init__(self, *arg, **kw):
        super().__init__(*arg, **kw)
        self['restock'] = Restock(kw['default']['restock']) if kw.get('default') and kw['default'].get('restock') else Restock()


    def clear_watch(self):
        super().clear_watch()
        self.update({'restock': Restock()})

    def extra_notification_token_values(self):
        values = super().extra_notification_token_values()
        values['restock'] = self.get('restock', {})

        values['restock']['previous_price'] = None
        if self.history_n >= 2:
            history = self.history
            if history and len(history) >=2:
                """Unfortunately for now timestamp is stored as string key"""
                sorted_keys = sorted(list(history), key=lambda x: int(x))
                sorted_keys.reverse()

                price_str = self.get_history_snapshot(timestamp=sorted_keys[-1])
                if price_str:
                    values['restock']['previous_price'] = get_price_from_history_str(price_str)
        return values

    def extra_notification_token_placeholder_info(self):
        values = super().extra_notification_token_placeholder_info()

        values.append(('restock.price', "Price detected"))
        values.append(('restock.in_stock', "In stock status"))
        values.append(('restock.original_price', "Original price at first check"))
        values.append(('restock.previous_price', "Previous price in history"))

        return values

