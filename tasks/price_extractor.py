"""
Price Extraction Module for TicketWatch

This module provides utilities for extracting price information from HTML content.
Supports single prices, price ranges, and various currency formats.

Features:
- Single price extraction (e.g., "$25", "25.00", "USD 25")
- Price range extraction (e.g., "$25 - $75", "$25-$75", "from $25 to $75")
- Multiple currency support (USD, EUR, GBP, CAD, AUD, JPY)
- Structured JSON output for storage in snapshots table

Usage:
    from tasks.price_extractor import PriceExtractor

    extractor = PriceExtractor()
    prices = extractor.extract_prices(html_content)
    # Returns: [{"price": 25.00, "currency": "USD", "type": "single"}, ...]
"""

import re
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation

# Try to use loguru if available
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# Currency Configuration
# =============================================================================

# Currency symbols to their ISO codes
CURRENCY_SYMBOLS: Dict[str, str] = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "C$": "CAD",
    "A$": "AUD",
    "CA$": "CAD",
    "AU$": "AUD",
    "US$": "USD",
    "CHF": "CHF",
    "₹": "INR",
    "R$": "BRL",
    "kr": "SEK",  # Could also be NOK, DKK - context dependent
}

# Currency codes that may appear as text
CURRENCY_CODES: Set[str] = {
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF", "INR", "BRL",
    "SEK", "NOK", "DKK", "NZD", "MXN", "SGD", "HKD", "KRW", "CNY"
}


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class ExtractedPrice:
    """Represents an extracted price from content."""
    price: float
    currency: str = "USD"
    price_type: str = "single"  # single, range_min, range_max
    original_text: str = ""
    confidence: float = 1.0  # 0.0 to 1.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class PriceRange:
    """Represents a price range."""
    min_price: float
    max_price: float
    currency: str = "USD"
    original_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "min_price": self.min_price,
            "max_price": self.max_price,
            "currency": self.currency,
            "original_text": self.original_text,
            "type": "range"
        }


# =============================================================================
# Price Extraction Patterns
# =============================================================================

class PricePatterns:
    """
    Regex patterns for extracting prices from text.

    Handles various formats:
    - $25, $25.00, $1,234.56
    - 25 USD, USD 25
    - €25, £25, ¥2500
    - $25 - $75 (ranges)
    - from $25 to $75 (ranges)
    """

    # Basic number pattern (handles commas in thousands)
    NUMBER = r'[\d,]+(?:\.\d{1,2})?'

    # Currency symbol pattern
    CURRENCY_SYMBOL = r'[\$€£¥₹]|C\$|A\$|CA\$|AU\$|US\$|R\$|CHF|kr'

    # Currency code pattern
    CURRENCY_CODE = r'(?:USD|EUR|GBP|JPY|CAD|AUD|CHF|INR|BRL|SEK|NOK|DKK|NZD|MXN|SGD|HKD|KRW|CNY)'

    # Single price with symbol before number: $25.00
    PRICE_SYMBOL_BEFORE = re.compile(
        rf'({CURRENCY_SYMBOL})\s*({NUMBER})',
        re.IGNORECASE
    )

    # Single price with symbol/code after number: 25.00 USD, 25 EUR
    PRICE_SYMBOL_AFTER = re.compile(
        rf'({NUMBER})\s*({CURRENCY_CODE})',
        re.IGNORECASE
    )

    # Price range with hyphen/dash: $25 - $75, $25-$75
    PRICE_RANGE_HYPHEN = re.compile(
        rf'({CURRENCY_SYMBOL})\s*({NUMBER})\s*[-–—]\s*({CURRENCY_SYMBOL})?\s*({NUMBER})',
        re.IGNORECASE
    )

    # Price range with "to": from $25 to $75, $25 to $75
    PRICE_RANGE_TO = re.compile(
        rf'(?:from\s+)?({CURRENCY_SYMBOL})\s*({NUMBER})\s+to\s+({CURRENCY_SYMBOL})?\s*({NUMBER})',
        re.IGNORECASE
    )

    # Price starting from: from $25, starting at $25
    PRICE_STARTING = re.compile(
        rf'(?:from|starting\s+(?:at|from)?)\s+({CURRENCY_SYMBOL})\s*({NUMBER})',
        re.IGNORECASE
    )

    # Ticket price context patterns (for better confidence)
    TICKET_CONTEXT = re.compile(
        r'(?:ticket|price|cost|admission|fee|general|vip|premium|standard|regular|'
        r'floor|balcony|orchestra|mezzanine|ga|seated|standing)',
        re.IGNORECASE
    )


# =============================================================================
# Price Extraction Implementation
# =============================================================================

class PriceExtractor:
    """
    Extracts price information from HTML or text content.

    This class provides methods for:
    - Extracting single prices
    - Extracting price ranges
    - Combining results into structured JSON

    Example:
        extractor = PriceExtractor()
        result = extractor.extract_all(html_content)
        # result = {
        #     "prices": [{"price": 25.00, "currency": "USD", ...}],
        #     "ranges": [{"min_price": 25.00, "max_price": 75.00, ...}],
        #     "summary": {"min": 25.00, "max": 75.00, "currency": "USD"}
        # }
    """

    def __init__(self, default_currency: str = "USD"):
        """
        Initialize the price extractor.

        Args:
            default_currency: Default currency code when none is detected.
        """
        self.default_currency = default_currency
        self._seen_prices: Set[Tuple[float, str]] = set()

    def extract_all(self, content: str, include_duplicates: bool = False) -> Dict[str, Any]:
        """
        Extract all price information from content.

        Args:
            content: HTML or text content to extract prices from.
            include_duplicates: If True, include duplicate prices.

        Returns:
            Dictionary with:
            - prices: List of individual prices
            - ranges: List of price ranges
            - summary: Summary with min/max prices
        """
        self._seen_prices.clear()

        # Clean HTML tags but preserve text
        text = self._strip_html(content)

        # Extract prices
        single_prices = self._extract_single_prices(text, include_duplicates)
        ranges = self._extract_ranges(text)

        # Build summary
        all_values = [p.price for p in single_prices]
        for r in ranges:
            all_values.extend([r.min_price, r.max_price])

        summary = {}
        if all_values:
            summary = {
                "min": min(all_values),
                "max": max(all_values),
                "currency": single_prices[0].currency if single_prices else (
                    ranges[0].currency if ranges else self.default_currency
                ),
                "count": len(single_prices) + len(ranges) * 2
            }

        return {
            "prices": [p.to_dict() for p in single_prices],
            "ranges": [r.to_dict() for r in ranges],
            "summary": summary
        }

    def extract_prices(self, content: str) -> List[Dict[str, Any]]:
        """
        Extract prices from content and return as list of dictionaries.

        This is the main method for extracting prices for storage.

        Args:
            content: HTML or text content.

        Returns:
            List of price dictionaries ready for JSON storage.
        """
        result = self.extract_all(content)

        prices = []

        # Add single prices
        for p in result.get("prices", []):
            prices.append({
                "price": p["price"],
                "currency": p["currency"],
                "type": p["price_type"],
                "original_text": p.get("original_text", "")
            })

        # Add ranges as two entries (min and max)
        for r in result.get("ranges", []):
            prices.append({
                "price": r["min_price"],
                "currency": r["currency"],
                "type": "range_min",
                "original_text": r.get("original_text", "")
            })
            prices.append({
                "price": r["max_price"],
                "currency": r["currency"],
                "type": "range_max",
                "original_text": r.get("original_text", "")
            })

        return prices

    def extract_price_range_string(self, content: str) -> Optional[str]:
        """
        Extract prices and format as a human-readable range string.

        Args:
            content: HTML or text content.

        Returns:
            Formatted string like "$25 - $75" or "$25" or None if no prices.
        """
        result = self.extract_all(content)

        all_prices = []
        currency = self.default_currency

        for p in result.get("prices", []):
            all_prices.append(p["price"])
            currency = p["currency"]

        for r in result.get("ranges", []):
            all_prices.extend([r["min_price"], r["max_price"]])
            currency = r["currency"]

        if not all_prices:
            return None

        min_price = min(all_prices)
        max_price = max(all_prices)

        symbol = self._get_currency_symbol(currency)

        if min_price == max_price:
            return f"{symbol}{min_price:.2f}"
        else:
            return f"{symbol}{min_price:.2f} - {symbol}{max_price:.2f}"

    def _extract_single_prices(
        self,
        text: str,
        include_duplicates: bool = False
    ) -> List[ExtractedPrice]:
        """Extract individual prices from text."""
        prices = []

        # Pattern: $25.00, €50, etc.
        for match in PricePatterns.PRICE_SYMBOL_BEFORE.finditer(text):
            symbol = match.group(1)
            number = match.group(2)

            price_value = self._parse_number(number)
            if price_value is None:
                continue

            currency = self._symbol_to_currency(symbol)

            if not include_duplicates:
                key = (price_value, currency)
                if key in self._seen_prices:
                    continue
                self._seen_prices.add(key)

            # Calculate confidence based on context
            context_start = max(0, match.start() - 50)
            context_end = min(len(text), match.end() + 50)
            context = text[context_start:context_end]
            confidence = 0.8 if PricePatterns.TICKET_CONTEXT.search(context) else 0.6

            prices.append(ExtractedPrice(
                price=price_value,
                currency=currency,
                price_type="single",
                original_text=match.group(0).strip(),
                confidence=confidence
            ))

        # Pattern: 25 USD, 50 EUR, etc.
        for match in PricePatterns.PRICE_SYMBOL_AFTER.finditer(text):
            number = match.group(1)
            currency = match.group(2).upper()

            price_value = self._parse_number(number)
            if price_value is None:
                continue

            if not include_duplicates:
                key = (price_value, currency)
                if key in self._seen_prices:
                    continue
                self._seen_prices.add(key)

            prices.append(ExtractedPrice(
                price=price_value,
                currency=currency,
                price_type="single",
                original_text=match.group(0).strip(),
                confidence=0.7
            ))

        return prices

    def _extract_ranges(self, text: str) -> List[PriceRange]:
        """Extract price ranges from text."""
        ranges = []

        # Pattern: $25 - $75, $25-$75
        for match in PricePatterns.PRICE_RANGE_HYPHEN.finditer(text):
            symbol1 = match.group(1)
            number1 = match.group(2)
            # symbol2 = match.group(3)  # Optional, may be None
            number2 = match.group(4)

            min_price = self._parse_number(number1)
            max_price = self._parse_number(number2)

            if min_price is None or max_price is None:
                continue

            # Ensure min <= max
            if min_price > max_price:
                min_price, max_price = max_price, min_price

            currency = self._symbol_to_currency(symbol1)

            ranges.append(PriceRange(
                min_price=min_price,
                max_price=max_price,
                currency=currency,
                original_text=match.group(0).strip()
            ))

        # Pattern: from $25 to $75
        for match in PricePatterns.PRICE_RANGE_TO.finditer(text):
            symbol1 = match.group(1)
            number1 = match.group(2)
            # symbol2 = match.group(3)  # Optional
            number2 = match.group(4)

            min_price = self._parse_number(number1)
            max_price = self._parse_number(number2)

            if min_price is None or max_price is None:
                continue

            if min_price > max_price:
                min_price, max_price = max_price, min_price

            currency = self._symbol_to_currency(symbol1)

            ranges.append(PriceRange(
                min_price=min_price,
                max_price=max_price,
                currency=currency,
                original_text=match.group(0).strip()
            ))

        return ranges

    def _parse_number(self, text: str) -> Optional[float]:
        """Parse a number string to float, handling commas."""
        if not text:
            return None

        try:
            # Remove commas used as thousands separator
            cleaned = text.replace(",", "")
            value = float(cleaned)

            # Sanity check: reject unreasonable prices
            if value <= 0 or value > 1000000:
                return None

            return round(value, 2)
        except (ValueError, InvalidOperation):
            return None

    def _symbol_to_currency(self, symbol: str) -> str:
        """Convert a currency symbol to ISO currency code."""
        symbol = symbol.strip()

        # Direct lookup
        if symbol in CURRENCY_SYMBOLS:
            return CURRENCY_SYMBOLS[symbol]

        # Check if it's already a code
        if symbol.upper() in CURRENCY_CODES:
            return symbol.upper()

        return self.default_currency

    def _get_currency_symbol(self, currency: str) -> str:
        """Get the symbol for a currency code."""
        symbol_map = {
            "USD": "$",
            "EUR": "€",
            "GBP": "£",
            "JPY": "¥",
            "CAD": "C$",
            "AUD": "A$",
            "CHF": "CHF ",
            "INR": "₹",
            "BRL": "R$",
        }
        return symbol_map.get(currency, f"{currency} ")

    def _strip_html(self, content: str) -> str:
        """Remove HTML tags while preserving text content."""
        # Remove script and style elements entirely
        text = re.sub(r'<script[^>]*>.*?</script>', ' ', content, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', ' ', text, flags=re.DOTALL | re.IGNORECASE)

        # Replace common block elements with spaces to preserve word boundaries
        text = re.sub(r'<(?:br|p|div|li|td|th|tr)[^>]*/?>', ' ', text, flags=re.IGNORECASE)

        # Remove remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode common HTML entities
        text = text.replace('&nbsp;', ' ')
        text = text.replace('&amp;', '&')
        text = text.replace('&lt;', '<')
        text = text.replace('&gt;', '>')
        text = text.replace('&quot;', '"')
        text = text.replace('&#39;', "'")

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)

        return text.strip()


# =============================================================================
# Convenience Functions
# =============================================================================

def extract_prices_from_html(html_content: str) -> List[Dict[str, Any]]:
    """
    Extract prices from HTML content.

    Convenience function for quick price extraction.

    Args:
        html_content: HTML content to extract prices from.

    Returns:
        List of price dictionaries.

    Example:
        >>> prices = extract_prices_from_html('<div class="price">$25.00</div>')
        >>> prices
        [{'price': 25.0, 'currency': 'USD', 'type': 'single', 'original_text': '$25.00'}]
    """
    extractor = PriceExtractor()
    return extractor.extract_prices(html_content)


def extract_price_summary(html_content: str) -> Dict[str, Any]:
    """
    Extract prices and return a summary.

    Args:
        html_content: HTML content to extract prices from.

    Returns:
        Dictionary with prices, ranges, and summary.
    """
    extractor = PriceExtractor()
    return extractor.extract_all(html_content)


def format_prices_for_display(prices: List[Dict[str, Any]]) -> str:
    """
    Format extracted prices for human-readable display.

    Args:
        prices: List of price dictionaries from extract_prices.

    Returns:
        Formatted string like "$25.00 - $75.00" or "$25.00"
    """
    if not prices:
        return "Price not available"

    all_values = []
    currency = "USD"

    for p in prices:
        if "price" in p:
            all_values.append(p["price"])
            currency = p.get("currency", "USD")
        elif "min_price" in p:
            all_values.extend([p["min_price"], p["max_price"]])
            currency = p.get("currency", "USD")

    if not all_values:
        return "Price not available"

    symbol_map = {
        "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
        "CAD": "C$", "AUD": "A$"
    }
    symbol = symbol_map.get(currency, f"{currency} ")

    min_val = min(all_values)
    max_val = max(all_values)

    if min_val == max_val:
        return f"{symbol}{min_val:.2f}"
    return f"{symbol}{min_val:.2f} - {symbol}{max_val:.2f}"


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == "__main__":
    # Test examples
    test_cases = [
        # Single prices
        '<span class="price">$25.00</span>',
        '<div>Tickets: $49.99 each</div>',
        '<p>Price: 35 USD</p>',
        '<span>€50</span>',
        '<div>£75.00</div>',

        # Price ranges
        '<span>$25 - $75</span>',
        '<div class="price-range">$25.00-$150.00</div>',
        '<p>From $30 to $100</p>',
        '<span>Tickets from $25 to $250</span>',

        # Multiple prices
        '''
        <div class="ticket-options">
            <div class="option">General Admission: $35</div>
            <div class="option">VIP: $75</div>
            <div class="option">Premium: $150</div>
        </div>
        ''',

        # Complex HTML
        '''
        <html>
        <body>
            <h1>Concert Tickets</h1>
            <div class="price-section">
                <span class="label">Price Range:</span>
                <span class="price">$49.99 - $199.99</span>
            </div>
            <script>var price = 50;</script>
        </body>
        </html>
        ''',
    ]

    extractor = PriceExtractor()

    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*60}")
        print(f"Test Case {i}:")
        print(f"Input: {test[:100]}...")

        result = extractor.extract_all(test)
        print(f"\nPrices found: {len(result['prices'])}")
        for p in result['prices']:
            print(f"  - {p}")

        print(f"Ranges found: {len(result['ranges'])}")
        for r in result['ranges']:
            print(f"  - {r}")

        if result['summary']:
            print(f"Summary: {result['summary']}")

        # Test formatted output
        prices = extractor.extract_prices(test)
        formatted = format_prices_for_display(prices)
        print(f"Formatted: {formatted}")
