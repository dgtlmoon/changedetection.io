#!/usr/bin/env python3

# python3 -m pytest changedetectionio/tests/unit/test_restock_filtered_price.py

import pytest

from changedetectionio.processors.restock_diff.filtered_price import (
    extract_price_from_filtered_text,
    NoPriceInFilteredText,
    MoreThanOnePriceInFilteredText,
)


@pytest.mark.parametrize("text, amount, currency", [
    ("Mondayprice$45.23 only", 45.23, "$"),
    ("Price: 1.299,00 €", 1299.0, "€"),
    ("€ 1 299,00", 1299.0, "€"),
    ("₪1,234", 1234.0, "₪"),
    ("USD 19.99", 19.99, "USD"),
    ("45 kr", 45.0, "kr"),
    # Bare numbers next to a currency amount are not the price
    ("Rated 4.5 stars, $19", 19.0, "$"),
    ("12 items left $9.99", 9.99, "$"),
    # The same price shown twice is still one price
    ("$45.23 $45.23", 45.23, "$"),
    # Only a number, nothing else it could be
    ("45.23", 45.23, None),
    ("\n  45.23 \n", 45.23, None),
])
def test_price_from_messy_text(text, amount, currency):
    assert extract_price_from_filtered_text(text) == (amount, currency)


@pytest.mark.parametrize("text, amounts", [
    ("was $59.99 now $45.23", [59.99, 45.23]),
    ("RRP $100 Save $20 $80", [100.0, 20.0, 80.0]),
    ("$13.12\n$2.62 per litre", [13.12, 2.62]),
])
def test_more_than_one_price_is_not_guessed(text, amounts):
    with pytest.raises(MoreThanOnePriceInFilteredText) as e:
        extract_price_from_filtered_text(text)
    assert e.value.amounts == amounts


@pytest.mark.parametrize("text", ["Out of stock", "", None, "Was 10 now 8"])
def test_no_price(text):
    with pytest.raises(NoPriceInFilteredText):
        extract_price_from_filtered_text(text)
