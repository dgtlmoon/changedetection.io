"""
Pick the product price out of the text a user's include_filters (CSS/XPath/JSON) matched.

Restock mode normally finds the price in the page's structured data (LD+JSON, microdata,
OpenGraph). When a shop has none, or has several prices, the user can point a filter straight
at the price instead (#2707). Whatever they selected is often messy - "Mondayprice$45.23 only",
"was $59.99 now $45.23", "Rated 4.5 stars, $19" - so:

- an amount written next to a currency ("$45.23", "45,00 €", "EUR 12") is a price,
  a bare number ("4.5", "12 items") is only used when it is the only number there is.
- more than one *different* currency amount is ambiguous, so it raises instead of guessing
  (taking the first would silently track the "was" price).

price_parser does the locale work ("1.299,00 €" vs "1,299.00"), it is imported lazily to
keep it out of every instance's startup memory.
"""
import re

# A run of digits with optional thousands/decimal separators: "45", "45.23", "1,299.00",
# "1.299,00", "1'299". A space only joins digit groups when exactly three digits follow
# ("1 299,00"), so "12 34" or "10 20" stay as two separate numbers.
_NUMBER_RE = re.compile(r"\d+(?:(?:[.,']|[   ](?=\d{3}(?!\d)))\d+)*")

# How far either side of a number to look for its currency symbol/code ("$", "€ ", "EUR ")
_CURRENCY_WINDOW = 4


class NoPriceInFilteredText(Exception):
    def __init__(self, text):
        self.text = text


class MoreThanOnePriceInFilteredText(Exception):
    def __init__(self, text, amounts):
        self.text = text
        self.amounts = amounts


def _candidates(text):
    """Yield (amount, currency) for every number in text, currency is None for a bare number."""
    from price_parser import Price
    from price_parser.parser import extract_currency_symbol

    for m in _NUMBER_RE.finditer(text):
        start, end = m.span()
        # Only the characters between this number and its neighbours, so "$20 $80" gives
        # "$20 " and " $80" rather than leaking one number's digits into the other's window.
        before = re.split(r"\d", text[max(0, start - _CURRENCY_WINDOW):start])[-1]
        after = re.split(r"\d", text[end:end + _CURRENCY_WINDOW])[0]
        window = f"{before}{m.group(0)}{after}"
        price = Price.fromstring(window)
        if price.amount is None:
            continue
        currency = extract_currency_symbol(window, None)
        yield price.amount, currency


def extract_price_from_filtered_text(text):
    """
    Return (amount: float, currency: str|None) from the filtered text.

    Raises NoPriceInFilteredText when there is no number at all (or only several bare
    numbers with no currency to tell which is the price), and MoreThanOnePriceInFilteredText
    when two or more different amounts both carry a currency.
    """
    text = (text or '').strip()
    found = list(_candidates(text))

    with_currency = []
    for amount, currency in found:
        if currency and amount not in [a for a, _ in with_currency]:
            with_currency.append((amount, currency))

    if len(with_currency) == 1:
        amount, currency = with_currency[0]
        return float(amount), currency

    if len(with_currency) > 1:
        raise MoreThanOnePriceInFilteredText(text=text, amounts=[float(a) for a, _ in with_currency])

    # No currency anywhere, a single bare number ("45.23") is still clearly the price
    if len({a for a, _ in found}) == 1:
        return float(found[0][0]), None

    raise NoPriceInFilteredText(text=text)
