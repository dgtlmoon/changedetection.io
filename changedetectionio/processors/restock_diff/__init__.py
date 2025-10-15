
from babel.numbers import parse_decimal
from changedetectionio.model.Watch import model as BaseWatch
from typing import Union
import re

class Restock(dict):

    def _normalize_currency_code(self, currency: str) -> str:
        """
        Normalize currency symbol or code to ISO 4217 code for consistency.
        Uses iso4217parse for accurate conversion.
        """
        if not currency:
            return currency

        # If already a 3-letter code, likely already normalized
        if len(currency) == 3 and currency.isupper():
            return currency

        try:
            import iso4217parse

            # Parse the currency - returns list of possible matches
            currencies = iso4217parse.parse(currency)

            if currencies:
                # For ambiguous symbols, prefer common currencies
                if currency == '$':
                    # Prefer USD for $ symbol
                    usd = [c for c in currencies if c.alpha3 == 'USD']
                    if usd:
                        return 'USD'
                elif currency == '£':
                    # Prefer GBP for £ symbol
                    gbp = [c for c in currencies if c.alpha3 == 'GBP']
                    if gbp:
                        return 'GBP'
                elif currency == '¥':
                    # Prefer JPY for ¥ symbol
                    jpy = [c for c in currencies if c.alpha3 == 'JPY']
                    if jpy:
                        return 'JPY'

                # Return first match for unambiguous symbols
                return currencies[0].alpha3
        except Exception:
            pass

        # Fallback: return as-is if can't normalize
        return currency

    def parse_currency(self, raw_value: str) -> Union[dict, None]:
        """
        Parse price and currency from text, handling messy formats with extra text.
        Returns dict with 'price' and 'currency' keys (ISO 4217 code), or None if parsing fails.
        """
        try:
            from price_parser import Price
            # price-parser handles:
            # - Extra text before/after ("Beginning at", "tax incl.")
            # - Various number formats (1 099,00 or 1,099.00)
            # - Currency symbols and codes
            price_obj = Price.fromstring(raw_value)

            if price_obj.amount is not None:
                result = {'price': float(price_obj.amount)}
                if price_obj.currency:
                    # Normalize currency symbol to ISO 4217 code for consistency with metadata
                    normalized_currency = self._normalize_currency_code(price_obj.currency)
                    result['currency'] = normalized_currency
                return result

        except Exception as e:
            from loguru import logger
            logger.trace(f"price-parser failed on '{raw_value}': {e}, falling back to manual parsing")

        # Fallback to existing manual parsing logic
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
            return {'price': float(parse_decimal(standardized_value, locale='en'))}

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
                parsed = self.parse_currency(raw_value=value)
                if parsed:
                    # Set the price value
                    value = parsed.get('price')
                    # Also set currency if found and not already set
                    if parsed.get('currency') and not self.get('currency'):
                        super().__setitem__('currency', parsed.get('currency'))
                else:
                    value = None

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

