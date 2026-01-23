"""
Event Data Extractor for ATC Page Monitor

This module provides CSS selector-based extraction of structured event data
from HTML content. It extracts fields like event name, artist, venue, date,
time, prices, and availability status.

Usage:
    from tasks.event_extractor import EventDataExtractor

    extractor = EventDataExtractor()

    # Define CSS selectors for each field
    css_selectors = {
        'event_name': 'h1.event-title',
        'artist': 'span.artist-name',
        'venue': 'div.venue-name',
        'event_date': 'span.event-date',
        'event_time': 'span.event-time',
        'current_price_low': 'span.price-min',
        'current_price_high': 'span.price-max',
        'is_sold_out': 'div.sold-out-badge',
    }

    # Extract data from HTML
    result = extractor.extract(html_content, css_selectors)

    # Apply manual overrides
    overrides = {'event_name': 'Manual Event Name'}
    final_data = extractor.apply_overrides(result, overrides)
"""

import re
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal, InvalidOperation
from typing import Any

try:
    from bs4 import BeautifulSoup

    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class ExtractionResult:
    """Result of extracting event data from HTML content."""

    event_name: str | None = None
    artist: str | None = None
    venue: str | None = None
    event_date: date | None = None
    event_time: time | None = None
    current_price_low: Decimal | None = None
    current_price_high: Decimal | None = None
    is_sold_out: bool = False

    # Metadata about extraction
    extraction_errors: dict[str, str] = field(default_factory=dict)
    raw_values: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'event_name': self.event_name,
            'artist': self.artist,
            'venue': self.venue,
            'event_date': self.event_date,
            'event_time': self.event_time,
            'current_price_low': self.current_price_low,
            'current_price_high': self.current_price_high,
            'is_sold_out': self.is_sold_out,
        }

    def has_changes(self, other: 'ExtractionResult') -> bool:
        """Check if this result differs from another."""
        return (
            self.event_name != other.event_name
            or self.artist != other.artist
            or self.venue != other.venue
            or self.event_date != other.event_date
            or self.event_time != other.event_time
            or self.current_price_low != other.current_price_low
            or self.current_price_high != other.current_price_high
            or self.is_sold_out != other.is_sold_out
        )

    def has_price_changes(self, other: 'ExtractionResult') -> bool:
        """Check if prices changed."""
        return (
            self.current_price_low != other.current_price_low
            or self.current_price_high != other.current_price_high
        )

    def has_availability_changes(self, other: 'ExtractionResult') -> bool:
        """Check if availability changed."""
        return self.is_sold_out != other.is_sold_out


# =============================================================================
# Event Data Extractor
# =============================================================================


class EventDataExtractor:
    """
    CSS selector-based extractor for structured event data.

    Extracts event information from HTML using configurable CSS selectors
    for each field. Supports type conversion for dates, times, and prices.
    """

    # Supported fields and their types
    FIELD_TYPES = {
        'event_name': 'text',
        'artist': 'text',
        'venue': 'text',
        'event_date': 'date',
        'event_time': 'time',
        'current_price_low': 'price',
        'current_price_high': 'price',
        'is_sold_out': 'boolean',
    }

    # Common date patterns
    DATE_PATTERNS = [
        # ISO format: 2024-01-15
        r'(\d{4})-(\d{2})-(\d{2})',
        # US format: 01/15/2024 or 1/15/2024
        r'(\d{1,2})/(\d{1,2})/(\d{4})',
        # Written format: January 15, 2024 or Jan 15, 2024
        r'(\w+)\s+(\d{1,2}),?\s+(\d{4})',
        # European format: 15/01/2024
        r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
        # Short written: Jan 15 (assumes current year)
        r'(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?',
    ]

    # Month name mapping
    MONTHS = {
        'january': 1,
        'jan': 1,
        'february': 2,
        'feb': 2,
        'march': 3,
        'mar': 3,
        'april': 4,
        'apr': 4,
        'may': 5,
        'june': 6,
        'jun': 6,
        'july': 7,
        'jul': 7,
        'august': 8,
        'aug': 8,
        'september': 9,
        'sep': 9,
        'sept': 9,
        'october': 10,
        'oct': 10,
        'november': 11,
        'nov': 11,
        'december': 12,
        'dec': 12,
    }

    # Common time patterns
    TIME_PATTERNS = [
        # 24-hour: 19:00 or 19:00:00
        r'(\d{1,2}):(\d{2})(?::(\d{2}))?',
        # 12-hour: 7:00 PM or 7:00PM or 7PM
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm|AM|PM)',
    ]

    # Price patterns
    PRICE_PATTERNS = [
        # $25.00 or $25
        r'\$\s*(\d+(?:\.\d{2})?)',
        # 25.00 USD or 25 USD
        r'(\d+(?:\.\d{2})?)\s*(?:USD|usd)',
        # Just numbers that look like prices
        r'(\d+\.\d{2})',
    ]

    # Sold out patterns (case-insensitive)
    SOLD_OUT_PATTERNS = [
        r'sold\s*out',
        r'no\s+tickets',
        r'unavailable',
        r'not\s+available',
        r'out\s+of\s+stock',
        r'no\s+longer\s+available',
    ]

    def __init__(self):
        """Initialize the extractor."""
        if not HAS_BS4:
            raise ImportError(
                "BeautifulSoup4 is required for EventDataExtractor. "
                "Install it with: pip install beautifulsoup4"
            )

    def extract(
        self,
        html_content: str,
        css_selectors: dict[str, str],
        overrides: dict[str, Any] | None = None,
    ) -> ExtractionResult:
        """
        Extract event data from HTML content using CSS selectors.

        Args:
            html_content: Raw HTML content to parse
            css_selectors: Dict mapping field names to CSS selectors
            overrides: Optional manual override values for any field

        Returns:
            ExtractionResult with extracted and converted values
        """
        result = ExtractionResult()

        if not html_content:
            result.extraction_errors['_general'] = 'Empty HTML content'
            return result

        try:
            soup = BeautifulSoup(html_content, 'html.parser')
        except Exception as e:
            result.extraction_errors['_general'] = f'HTML parsing error: {e}'
            return result

        # Extract each field using its CSS selector
        for field_name, field_type in self.FIELD_TYPES.items():
            selector = css_selectors.get(field_name)
            if not selector:
                continue

            try:
                raw_value = self._extract_text(soup, selector)
                if raw_value:
                    result.raw_values[field_name] = raw_value
                    converted_value = self._convert_value(raw_value, field_type)
                    setattr(result, field_name, converted_value)
            except Exception as e:
                result.extraction_errors[field_name] = str(e)
                logger.debug(f"Extraction error for {field_name}: {e}")

        # Apply manual overrides
        if overrides:
            result = self.apply_overrides(result, overrides)

        return result

    def apply_overrides(
        self, result: ExtractionResult, overrides: dict[str, Any]
    ) -> ExtractionResult:
        """
        Apply manual override values to extraction result.

        Args:
            result: ExtractionResult to modify
            overrides: Dict of field_name -> override_value

        Returns:
            Modified ExtractionResult
        """
        for field_name, value in overrides.items():
            if field_name not in self.FIELD_TYPES:
                continue

            if value is None or value == '':
                continue

            field_type = self.FIELD_TYPES[field_name]

            try:
                # Convert the override value to the correct type
                if isinstance(value, str):
                    converted_value = self._convert_value(value, field_type)
                else:
                    converted_value = value

                setattr(result, field_name, converted_value)
            except Exception as e:
                result.extraction_errors[f'{field_name}_override'] = str(e)

        return result

    def _extract_text(self, soup: BeautifulSoup, selector: str) -> str | None:
        """
        Extract text content from an element matching the CSS selector.

        Args:
            soup: BeautifulSoup object
            selector: CSS selector string

        Returns:
            Extracted text or None if not found
        """
        element = soup.select_one(selector)
        if element:
            # Get text content, strip whitespace
            text = element.get_text(strip=True)
            # Normalize whitespace
            text = ' '.join(text.split())
            return text if text else None
        return None

    def _convert_value(self, raw_value: str, field_type: str) -> Any:
        """
        Convert raw string value to the appropriate type.

        Args:
            raw_value: Raw string value from HTML
            field_type: Target type ('text', 'date', 'time', 'price', 'boolean')

        Returns:
            Converted value
        """
        if field_type == 'text':
            return raw_value.strip()

        elif field_type == 'date':
            return self._parse_date(raw_value)

        elif field_type == 'time':
            return self._parse_time(raw_value)

        elif field_type == 'price':
            return self._parse_price(raw_value)

        elif field_type == 'boolean':
            return self._parse_sold_out(raw_value)

        return raw_value

    def _parse_date(self, value: str) -> date | None:
        """
        Parse a date string into a date object.

        Args:
            value: Date string in various formats

        Returns:
            date object or None if parsing fails
        """
        value = value.strip()

        # Try ISO format first: 2024-01-15
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})', value)
        if match:
            try:
                return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                pass

        # Try US format: 01/15/2024
        match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', value)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(1)), int(match.group(2)))
            except ValueError:
                pass

        # Try European format: 15.01.2024
        match = re.search(r'(\d{1,2})\.(\d{1,2})\.(\d{4})', value)
        if match:
            try:
                return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))
            except ValueError:
                pass

        # Try written format: January 15, 2024 or Jan 15, 2024
        match = re.search(r'(\w+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})', value, re.IGNORECASE)
        if match:
            month_name = match.group(1).lower()
            if month_name in self.MONTHS:
                try:
                    return date(
                        int(match.group(3)), self.MONTHS[month_name], int(match.group(2))
                    )
                except ValueError:
                    pass

        # Try short written format: Jan 15 (assumes current year)
        match = re.search(r'(\w{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?', value, re.IGNORECASE)
        if match:
            month_name = match.group(1).lower()
            if month_name in self.MONTHS:
                try:
                    from datetime import datetime

                    current_year = datetime.now().year
                    return date(current_year, self.MONTHS[month_name], int(match.group(2)))
                except ValueError:
                    pass

        return None

    def _parse_time(self, value: str) -> time | None:
        """
        Parse a time string into a time object.

        Args:
            value: Time string in various formats

        Returns:
            time object or None if parsing fails
        """
        value = value.strip()

        # Try 12-hour format with AM/PM: 7:00 PM or 7PM
        match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', value, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            is_pm = match.group(3).lower() == 'pm'

            # Convert to 24-hour
            if is_pm and hour < 12:
                hour += 12
            elif not is_pm and hour == 12:
                hour = 0

            try:
                return time(hour, minute)
            except ValueError:
                pass

        # Try 24-hour format: 19:00 or 19:00:00
        match = re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', value)
        if match:
            try:
                hour = int(match.group(1))
                minute = int(match.group(2))
                second = int(match.group(3) or 0)
                return time(hour, minute, second)
            except ValueError:
                pass

        return None

    def _parse_price(self, value: str) -> Decimal | None:
        """
        Parse a price string into a Decimal.

        Args:
            value: Price string (e.g., "$25.00", "25 USD", "25.00", "$1,250.00")

        Returns:
            Decimal or None if parsing fails
        """
        value = value.strip()

        # Remove commas from number strings (e.g., "$1,250.00" -> "$1250.00")
        value_no_commas = value.replace(',', '')

        # Try common price patterns
        for pattern in self.PRICE_PATTERNS:
            match = re.search(pattern, value_no_commas)
            if match:
                try:
                    return Decimal(match.group(1))
                except InvalidOperation:
                    pass

        # Try to find any number that looks like a price
        match = re.search(r'(\d+(?:\.\d{2})?)', value_no_commas)
        if match:
            try:
                return Decimal(match.group(1))
            except InvalidOperation:
                pass

        return None

    def _parse_sold_out(self, value: str) -> bool:
        """
        Determine if the value indicates sold out status.

        Args:
            value: Text content to check

        Returns:
            True if sold out, False otherwise
        """
        value = value.lower().strip()

        for pattern in self.SOLD_OUT_PATTERNS:
            if re.search(pattern, value, re.IGNORECASE):
                return True

        return False

    def extract_from_event(
        self,
        html_content: str,
        event_css_selectors: dict[str, str] | None,
        event_extra_config: dict[str, Any] | None,
    ) -> ExtractionResult:
        """
        Extract event data using an Event model's configuration.

        This is a convenience method that gets CSS selectors from the event's
        css_selectors field and manual overrides from extra_config.

        Args:
            html_content: Raw HTML content
            event_css_selectors: Event's css_selectors JSONB field
            event_extra_config: Event's extra_config JSONB field

        Returns:
            ExtractionResult with extracted data
        """
        css_selectors = event_css_selectors or {}
        overrides = {}

        # Get manual overrides from extra_config
        if event_extra_config:
            manual_overrides = event_extra_config.get('manual_overrides', {})
            if isinstance(manual_overrides, dict):
                overrides = manual_overrides

        return self.extract(html_content, css_selectors, overrides)


# =============================================================================
# Utility Functions
# =============================================================================


def create_default_css_selectors() -> dict[str, str]:
    """
    Create a default CSS selectors template.

    Returns:
        Dict with empty CSS selectors for each supported field
    """
    return {
        'event_name': '',
        'artist': '',
        'venue': '',
        'event_date': '',
        'event_time': '',
        'current_price_low': '',
        'current_price_high': '',
        'is_sold_out': '',
    }


def validate_css_selector(selector: str) -> bool:
    """
    Validate that a CSS selector is syntactically valid.

    Args:
        selector: CSS selector string

    Returns:
        True if valid, False otherwise
    """
    if not HAS_BS4:
        return True  # Can't validate without BS4

    if not selector or not selector.strip():
        return True  # Empty selectors are valid (means "don't extract this field")

    try:
        soup = BeautifulSoup('<html></html>', 'html.parser')
        soup.select(selector)
        return True
    except Exception:
        return False


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == '__main__':
    # Test the extractor with sample HTML
    sample_html = """
    <html>
    <head><title>Test Event</title></head>
    <body>
        <h1 class="event-title">Taylor Swift - The Eras Tour</h1>
        <div class="event-details">
            <span class="artist-name">Taylor Swift</span>
            <div class="venue-name">SoFi Stadium</div>
            <span class="event-date">January 15, 2024</span>
            <span class="event-time">7:30 PM</span>
        </div>
        <div class="pricing">
            <span class="price-min">$125.00</span>
            <span class="price-max">$450.00</span>
        </div>
    </body>
    </html>
    """

    css_selectors = {
        'event_name': 'h1.event-title',
        'artist': 'span.artist-name',
        'venue': 'div.venue-name',
        'event_date': 'span.event-date',
        'event_time': 'span.event-time',
        'current_price_low': 'span.price-min',
        'current_price_high': 'span.price-max',
        'is_sold_out': 'div.sold-out-badge',
    }

    extractor = EventDataExtractor()
    result = extractor.extract(sample_html, css_selectors)

    print("Extraction Result:")
    print(f"  Event Name: {result.event_name}")
    print(f"  Artist: {result.artist}")
    print(f"  Venue: {result.venue}")
    print(f"  Date: {result.event_date}")
    print(f"  Time: {result.event_time}")
    print(f"  Price Low: ${result.current_price_low}")
    print(f"  Price High: ${result.current_price_high}")
    print(f"  Sold Out: {result.is_sold_out}")
    print(f"  Raw Values: {result.raw_values}")
    print(f"  Errors: {result.extraction_errors}")
