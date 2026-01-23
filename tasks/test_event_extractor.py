"""
Tests for Event Data Extractor (US-007)

Tests CSS selector-based extraction of event data including:
- Text field extraction (event_name, artist, venue)
- Date parsing in multiple formats
- Time parsing in 12-hour and 24-hour formats
- Price extraction from various formats
- Sold out detection
- Manual overrides
- Integration with Event model
"""

import pytest
from datetime import date, time
from decimal import Decimal

from tasks.event_extractor import (
    EventDataExtractor,
    ExtractionResult,
    create_default_css_selectors,
    validate_css_selector,
)


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def extractor():
    """Create an EventDataExtractor instance."""
    return EventDataExtractor()


@pytest.fixture
def sample_html():
    """Sample HTML for testing basic extraction."""
    return """
    <html>
    <head><title>Event Page</title></head>
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


@pytest.fixture
def sample_selectors():
    """CSS selectors for sample HTML."""
    return {
        'event_name': 'h1.event-title',
        'artist': 'span.artist-name',
        'venue': 'div.venue-name',
        'event_date': 'span.event-date',
        'event_time': 'span.event-time',
        'current_price_low': 'span.price-min',
        'current_price_high': 'span.price-max',
        'is_sold_out': 'div.sold-out-badge',
    }


# =============================================================================
# Basic Extraction Tests
# =============================================================================


class TestBasicExtraction:
    """Tests for basic field extraction."""

    def test_extract_text_fields(self, extractor, sample_html, sample_selectors):
        """Test extraction of text fields (event_name, artist, venue)."""
        result = extractor.extract(sample_html, sample_selectors)

        assert result.event_name == "Taylor Swift - The Eras Tour"
        assert result.artist == "Taylor Swift"
        assert result.venue == "SoFi Stadium"

    def test_extract_with_empty_html(self, extractor, sample_selectors):
        """Test extraction with empty HTML content."""
        result = extractor.extract("", sample_selectors)

        assert result.event_name is None
        assert result.artist is None
        assert '_general' in result.extraction_errors

    def test_extract_with_invalid_html(self, extractor, sample_selectors):
        """Test extraction with malformed HTML."""
        html = "<html><body><div>Unclosed tags"
        result = extractor.extract(html, sample_selectors)

        # Should not crash, may have None values
        assert isinstance(result, ExtractionResult)

    def test_extract_with_missing_elements(self, extractor):
        """Test extraction when some elements are missing."""
        html = """
        <html><body>
            <h1 class="event-title">Concert Name</h1>
        </body></html>
        """
        selectors = {
            'event_name': 'h1.event-title',
            'artist': 'span.artist-name',  # Not present
        }

        result = extractor.extract(html, selectors)

        assert result.event_name == "Concert Name"
        assert result.artist is None

    def test_extract_with_empty_selectors(self, extractor, sample_html):
        """Test extraction with empty selector dict."""
        result = extractor.extract(sample_html, {})

        assert result.event_name is None
        assert result.artist is None
        assert result.venue is None

    def test_raw_values_stored(self, extractor, sample_html, sample_selectors):
        """Test that raw extracted values are stored."""
        result = extractor.extract(sample_html, sample_selectors)

        assert 'event_name' in result.raw_values
        assert 'Taylor Swift - The Eras Tour' in result.raw_values['event_name']


# =============================================================================
# Date Parsing Tests
# =============================================================================


class TestDateParsing:
    """Tests for date parsing in various formats."""

    @pytest.mark.parametrize(
        "date_str,expected",
        [
            # ISO format
            ("2024-01-15", date(2024, 1, 15)),
            ("2024-12-31", date(2024, 12, 31)),
            # US format
            ("01/15/2024", date(2024, 1, 15)),
            ("1/5/2024", date(2024, 1, 5)),
            ("12/31/2024", date(2024, 12, 31)),
            # European format
            ("15.01.2024", date(2024, 1, 15)),
            ("31.12.2024", date(2024, 12, 31)),
            # Written formats
            ("January 15, 2024", date(2024, 1, 15)),
            ("Jan 15, 2024", date(2024, 1, 15)),
            ("December 31, 2024", date(2024, 12, 31)),
            ("Dec 31 2024", date(2024, 12, 31)),
            # With ordinals
            ("January 15th, 2024", date(2024, 1, 15)),
            ("Jan 1st, 2024", date(2024, 1, 1)),
            ("March 3rd, 2024", date(2024, 3, 3)),
            ("May 22nd, 2024", date(2024, 5, 22)),
        ],
    )
    def test_date_formats(self, extractor, date_str, expected):
        """Test parsing of various date formats."""
        html = f'<span class="date">{date_str}</span>'
        selectors = {'event_date': 'span.date'}

        result = extractor.extract(html, selectors)

        assert result.event_date == expected

    def test_date_with_surrounding_text(self, extractor):
        """Test date extraction from text with surrounding content."""
        html = '<span class="date">Event Date: January 15, 2024 - Save the date!</span>'
        selectors = {'event_date': 'span.date'}

        result = extractor.extract(html, selectors)

        assert result.event_date == date(2024, 1, 15)

    def test_invalid_date(self, extractor):
        """Test handling of invalid date strings."""
        html = '<span class="date">Not a real date</span>'
        selectors = {'event_date': 'span.date'}

        result = extractor.extract(html, selectors)

        assert result.event_date is None


# =============================================================================
# Time Parsing Tests
# =============================================================================


class TestTimeParsing:
    """Tests for time parsing in various formats."""

    @pytest.mark.parametrize(
        "time_str,expected",
        [
            # 12-hour format
            ("7:00 PM", time(19, 0)),
            ("7:30 PM", time(19, 30)),
            ("12:00 PM", time(12, 0)),
            ("12:00 AM", time(0, 0)),
            ("7:00 AM", time(7, 0)),
            ("7PM", time(19, 0)),
            ("7 PM", time(19, 0)),
            ("7:00pm", time(19, 0)),
            ("11:59 PM", time(23, 59)),
            # 24-hour format
            ("19:00", time(19, 0)),
            ("19:30", time(19, 30)),
            ("00:00", time(0, 0)),
            ("23:59", time(23, 59)),
            ("19:00:00", time(19, 0, 0)),
            ("9:00", time(9, 0)),
        ],
    )
    def test_time_formats(self, extractor, time_str, expected):
        """Test parsing of various time formats."""
        html = f'<span class="time">{time_str}</span>'
        selectors = {'event_time': 'span.time'}

        result = extractor.extract(html, selectors)

        assert result.event_time == expected

    def test_time_with_surrounding_text(self, extractor):
        """Test time extraction from text with surrounding content."""
        html = '<span class="time">Doors open at 7:00 PM</span>'
        selectors = {'event_time': 'span.time'}

        result = extractor.extract(html, selectors)

        assert result.event_time == time(19, 0)

    def test_invalid_time(self, extractor):
        """Test handling of invalid time strings."""
        html = '<span class="time">TBD</span>'
        selectors = {'event_time': 'span.time'}

        result = extractor.extract(html, selectors)

        assert result.event_time is None


# =============================================================================
# Price Parsing Tests
# =============================================================================


class TestPriceParsing:
    """Tests for price parsing."""

    @pytest.mark.parametrize(
        "price_str,expected",
        [
            # USD with dollar sign
            ("$25.00", Decimal("25.00")),
            ("$125.00", Decimal("125.00")),
            ("$1,250.00", Decimal("1250.00")),
            ("$ 25.00", Decimal("25.00")),
            ("$25", Decimal("25")),
            # USD suffix
            ("25.00 USD", Decimal("25.00")),
            ("125 USD", Decimal("125")),
            # Plain numbers
            ("25.00", Decimal("25.00")),
            ("125.00", Decimal("125.00")),
        ],
    )
    def test_price_formats(self, extractor, price_str, expected):
        """Test parsing of various price formats."""
        html = f'<span class="price">{price_str}</span>'
        selectors = {'current_price_low': 'span.price'}

        result = extractor.extract(html, selectors)

        assert result.current_price_low == expected

    def test_price_with_text(self, extractor):
        """Test price extraction from text with surrounding content."""
        html = '<span class="price">Starting at $125.00</span>'
        selectors = {'current_price_low': 'span.price'}

        result = extractor.extract(html, selectors)

        assert result.current_price_low == Decimal("125.00")

    def test_price_range_extraction(self, extractor):
        """Test extracting low and high prices."""
        html = """
        <div class="pricing">
            <span class="low">$50.00</span>
            <span class="high">$200.00</span>
        </div>
        """
        selectors = {
            'current_price_low': 'span.low',
            'current_price_high': 'span.high',
        }

        result = extractor.extract(html, selectors)

        assert result.current_price_low == Decimal("50.00")
        assert result.current_price_high == Decimal("200.00")


# =============================================================================
# Sold Out Detection Tests
# =============================================================================


class TestSoldOutDetection:
    """Tests for sold out status detection."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Sold Out", True),
            ("SOLD OUT", True),
            ("sold out", True),
            ("Sold out!", True),
            ("This event is sold out", True),
            ("No Tickets Available", True),
            ("Unavailable", True),
            ("Not Available", True),
            ("Out of Stock", True),
            ("No longer available", True),
            # Not sold out
            ("Buy Tickets", False),
            ("Available", False),
            ("In Stock", False),
            ("", False),
        ],
    )
    def test_sold_out_patterns(self, extractor, text, expected):
        """Test detection of various sold out indicators."""
        html = f'<div class="status">{text}</div>'
        selectors = {'is_sold_out': 'div.status'}

        result = extractor.extract(html, selectors)

        assert result.is_sold_out == expected

    def test_sold_out_badge_present(self, extractor):
        """Test sold out when badge element exists."""
        html = '<div class="sold-out-badge">SOLD OUT</div>'
        selectors = {'is_sold_out': 'div.sold-out-badge'}

        result = extractor.extract(html, selectors)

        assert result.is_sold_out is True

    def test_sold_out_badge_absent(self, extractor):
        """Test not sold out when badge element is missing."""
        html = '<div class="available">Buy Now</div>'
        selectors = {'is_sold_out': 'div.sold-out-badge'}

        result = extractor.extract(html, selectors)

        # Element not found, so is_sold_out stays False
        assert result.is_sold_out is False


# =============================================================================
# Manual Override Tests
# =============================================================================


class TestManualOverrides:
    """Tests for manual override functionality."""

    def test_apply_overrides(self, extractor, sample_html, sample_selectors):
        """Test that manual overrides replace extracted values."""
        result = extractor.extract(sample_html, sample_selectors)

        assert result.event_name == "Taylor Swift - The Eras Tour"

        overrides = {'event_name': 'Custom Event Name'}
        result = extractor.apply_overrides(result, overrides)

        assert result.event_name == "Custom Event Name"

    def test_override_with_type_conversion(self, extractor):
        """Test that overrides are type-converted."""
        result = ExtractionResult()
        overrides = {
            'event_date': 'March 20, 2024',
            'current_price_low': '$100.00',
        }

        result = extractor.apply_overrides(result, overrides)

        assert result.event_date == date(2024, 3, 20)
        assert result.current_price_low == Decimal("100.00")

    def test_override_null_value(self, extractor, sample_html, sample_selectors):
        """Test that None overrides don't change values."""
        result = extractor.extract(sample_html, sample_selectors)
        original_name = result.event_name

        overrides = {'event_name': None}
        result = extractor.apply_overrides(result, overrides)

        assert result.event_name == original_name

    def test_override_empty_string(self, extractor, sample_html, sample_selectors):
        """Test that empty string overrides don't change values."""
        result = extractor.extract(sample_html, sample_selectors)
        original_name = result.event_name

        overrides = {'event_name': ''}
        result = extractor.apply_overrides(result, overrides)

        assert result.event_name == original_name

    def test_extract_with_overrides(self, extractor, sample_html, sample_selectors):
        """Test extraction with overrides provided directly."""
        overrides = {'venue': 'Custom Venue'}
        result = extractor.extract(sample_html, sample_selectors, overrides)

        assert result.event_name == "Taylor Swift - The Eras Tour"  # From HTML
        assert result.venue == "Custom Venue"  # From override


# =============================================================================
# ExtractionResult Tests
# =============================================================================


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = ExtractionResult(
            event_name="Test Event",
            artist="Test Artist",
            venue="Test Venue",
            event_date=date(2024, 1, 15),
            event_time=time(19, 30),
            current_price_low=Decimal("50.00"),
            current_price_high=Decimal("100.00"),
            is_sold_out=False,
        )

        d = result.to_dict()

        assert d['event_name'] == "Test Event"
        assert d['artist'] == "Test Artist"
        assert d['event_date'] == date(2024, 1, 15)
        assert d['current_price_low'] == Decimal("50.00")
        assert d['is_sold_out'] is False

    def test_has_changes(self):
        """Test change detection between two results."""
        result1 = ExtractionResult(event_name="Event 1", current_price_low=Decimal("50.00"))
        result2 = ExtractionResult(event_name="Event 1", current_price_low=Decimal("50.00"))
        result3 = ExtractionResult(event_name="Event 2", current_price_low=Decimal("50.00"))
        result4 = ExtractionResult(event_name="Event 1", current_price_low=Decimal("75.00"))

        assert not result1.has_changes(result2)  # Same
        assert result1.has_changes(result3)  # Name changed
        assert result1.has_changes(result4)  # Price changed

    def test_has_price_changes(self):
        """Test price change detection."""
        result1 = ExtractionResult(current_price_low=Decimal("50.00"))
        result2 = ExtractionResult(current_price_low=Decimal("50.00"))
        result3 = ExtractionResult(current_price_low=Decimal("75.00"))

        assert not result1.has_price_changes(result2)
        assert result1.has_price_changes(result3)

    def test_has_availability_changes(self):
        """Test availability change detection."""
        result1 = ExtractionResult(is_sold_out=False)
        result2 = ExtractionResult(is_sold_out=False)
        result3 = ExtractionResult(is_sold_out=True)

        assert not result1.has_availability_changes(result2)
        assert result1.has_availability_changes(result3)


# =============================================================================
# Utility Function Tests
# =============================================================================


class TestUtilityFunctions:
    """Tests for utility functions."""

    def test_create_default_css_selectors(self):
        """Test creation of default selector template."""
        selectors = create_default_css_selectors()

        assert 'event_name' in selectors
        assert 'artist' in selectors
        assert 'venue' in selectors
        assert 'event_date' in selectors
        assert 'event_time' in selectors
        assert 'current_price_low' in selectors
        assert 'current_price_high' in selectors
        assert 'is_sold_out' in selectors

        # All should be empty strings
        for value in selectors.values():
            assert value == ''

    def test_validate_css_selector_valid(self):
        """Test validation of valid CSS selectors."""
        assert validate_css_selector('h1.title') is True
        assert validate_css_selector('div#main') is True
        assert validate_css_selector('span.price-low') is True
        assert validate_css_selector('div > span.nested') is True
        assert validate_css_selector('[data-price]') is True
        assert validate_css_selector('') is True  # Empty is valid

    def test_validate_css_selector_invalid(self):
        """Test validation of invalid CSS selectors."""
        # BeautifulSoup is permissive, so most "invalid" selectors still work
        # This test just ensures the function doesn't crash
        assert isinstance(validate_css_selector('h1['), bool)


# =============================================================================
# Integration Tests
# =============================================================================


class TestIntegration:
    """Integration tests with realistic HTML."""

    def test_ticketmaster_style_page(self, extractor):
        """Test extraction from Ticketmaster-style HTML."""
        html = """
        <html>
        <body>
            <div class="event-header">
                <h1 data-testid="event-title">Beyonce - Renaissance World Tour</h1>
                <div class="artist-info">
                    <span class="performer">Beyonce</span>
                </div>
            </div>
            <div class="event-info">
                <div class="venue-details">
                    <span class="venue-name">Mercedes-Benz Stadium</span>
                    <span class="venue-city">Atlanta, GA</span>
                </div>
                <div class="date-time">
                    <span class="event-date">Sat, Sep 14, 2024</span>
                    <span class="event-time">7:00 PM</span>
                </div>
            </div>
            <div class="pricing-section">
                <span class="price-range">$89.50 - $899.50</span>
            </div>
        </body>
        </html>
        """

        selectors = {
            'event_name': 'h1[data-testid="event-title"]',
            'artist': 'span.performer',
            'venue': 'span.venue-name',
            'event_date': 'span.event-date',
            'event_time': 'span.event-time',
        }

        result = extractor.extract(html, selectors)

        assert result.event_name == "Beyonce - Renaissance World Tour"
        assert result.artist == "Beyonce"
        assert result.venue == "Mercedes-Benz Stadium"
        assert result.event_date == date(2024, 9, 14)
        assert result.event_time == time(19, 0)

    def test_sold_out_event(self, extractor):
        """Test extraction from a sold out event page."""
        html = """
        <html>
        <body>
            <h1 class="event-name">Popular Concert</h1>
            <div class="availability">
                <span class="status sold-out">SOLD OUT</span>
            </div>
            <div class="pricing">
                <span class="original-price">$150.00</span>
            </div>
        </body>
        </html>
        """

        selectors = {
            'event_name': 'h1.event-name',
            'is_sold_out': 'span.status',
            'current_price_low': 'span.original-price',
        }

        result = extractor.extract(html, selectors)

        assert result.event_name == "Popular Concert"
        assert result.is_sold_out is True
        assert result.current_price_low == Decimal("150.00")

    def test_extract_from_event_helper(self, extractor):
        """Test the extract_from_event convenience method."""
        html = """
        <html>
        <body>
            <h1 class="title">Test Event</h1>
            <span class="price">$50.00</span>
        </body>
        </html>
        """

        css_selectors = {
            'event_name': 'h1.title',
            'current_price_low': 'span.price',
        }

        extra_config = {
            'manual_overrides': {
                'venue': 'Override Venue',
            }
        }

        result = extractor.extract_from_event(html, css_selectors, extra_config)

        assert result.event_name == "Test Event"
        assert result.current_price_low == Decimal("50.00")
        assert result.venue == "Override Venue"


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])
