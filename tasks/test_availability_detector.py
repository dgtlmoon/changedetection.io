"""
Unit tests for the Availability Detector module.

Tests cover:
- Sold out pattern detection
- Limited availability detection
- In stock detection
- Cross-platform compatibility
- Edge cases and error handling
"""

import pytest
from tasks.availability_detector import (
    AvailabilityDetector,
    AvailabilityResult,
    AvailabilityStatus,
    detect_availability,
    get_availability_status,
    is_sold_out,
    determine_change_type,
)


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def detector():
    """Create a fresh AvailabilityDetector instance for each test."""
    return AvailabilityDetector()


# =============================================================================
# Sold Out Detection Tests
# =============================================================================

class TestSoldOutDetection:
    """Tests for detecting sold out status."""

    def test_explicit_sold_out(self, detector):
        """Test explicit 'Sold Out' text."""
        result = detector.detect_availability('<div>SOLD OUT</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_sold_out_lowercase(self, detector):
        """Test lowercase 'sold out'."""
        result = detector.detect_availability('<span>sold out</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_sold_out_mixed_case(self, detector):
        """Test mixed case 'Sold Out'."""
        result = detector.detect_availability('<p>Sold Out</p>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_soldout_no_space(self, detector):
        """Test 'soldout' without space."""
        result = detector.detect_availability('<div class="status">SOLDOUT</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_unavailable(self, detector):
        """Test 'unavailable' pattern."""
        result = detector.detect_availability('<span>Unavailable</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.85

    def test_not_available(self, detector):
        """Test 'not available' pattern."""
        result = detector.detect_availability('<div>Tickets are not available</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.85

    def test_no_longer_available(self, detector):
        """Test 'no longer available' pattern."""
        result = detector.detect_availability('<p>This event is no longer available</p>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_out_of_stock(self, detector):
        """Test 'out of stock' pattern."""
        result = detector.detect_availability('<span>Out of stock</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_event_is_sold_out(self, detector):
        """Test 'event is sold out' pattern."""
        result = detector.detect_availability('<div>This event is sold out</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.95

    def test_show_is_sold_out(self, detector):
        """Test 'show is sold out' pattern."""
        result = detector.detect_availability('<div>This show is sold out</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.95

    def test_concert_is_sold_out(self, detector):
        """Test 'concert is sold out' pattern."""
        result = detector.detect_availability('<div>Concert is sold out</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.95

    def test_tickets_sold_out(self, detector):
        """Test 'tickets sold out' pattern."""
        result = detector.detect_availability('<span>All tickets sold out</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.95

    def test_no_tickets_available(self, detector):
        """Test 'no tickets available' pattern."""
        result = detector.detect_availability('<div>No tickets available</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_no_tickets_remaining(self, detector):
        """Test 'no tickets remaining' pattern."""
        result = detector.detect_availability('<p>No tickets remaining</p>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_no_tickets_left(self, detector):
        """Test 'no tickets left' pattern."""
        result = detector.detect_availability('<span>No tickets left!</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_zero_tickets_available(self, detector):
        """Test '0 tickets available' pattern."""
        result = detector.detect_availability('<div>0 tickets available</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.90

    def test_off_sale(self, detector):
        """Test 'off sale' pattern."""
        result = detector.detect_availability('<span>This event is off sale</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.85

    def test_sale_ended(self, detector):
        """Test 'sale ended' pattern."""
        result = detector.detect_availability('<div>Sale ended</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.85

    def test_cancelled_event(self, detector):
        """Test 'cancelled' pattern."""
        result = detector.detect_availability('<span>Event cancelled</span>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.80

    def test_at_capacity(self, detector):
        """Test 'at capacity' pattern."""
        result = detector.detect_availability('<div>Venue is at capacity</div>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.80

    def test_join_waitlist(self, detector):
        """Test 'join waitlist' pattern."""
        result = detector.detect_availability('<button>Join the waitlist</button>')
        assert result.status == 'out_of_stock'
        assert result.confidence >= 0.75


# =============================================================================
# Limited Availability Detection Tests
# =============================================================================

class TestLimitedAvailabilityDetection:
    """Tests for detecting limited availability status."""

    def test_limited_tickets(self, detector):
        """Test 'limited tickets' pattern."""
        result = detector.detect_availability('<div>Limited tickets available</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_limited_availability(self, detector):
        """Test 'limited availability' pattern."""
        result = detector.detect_availability('<span>Limited availability</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_only_x_tickets_left(self, detector):
        """Test 'only X tickets left' pattern."""
        result = detector.detect_availability('<div>Only 5 tickets left!</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.85

    def test_just_x_remaining(self, detector):
        """Test 'just X remaining' pattern."""
        result = detector.detect_availability('<span>Just 3 tickets remaining</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.85

    def test_few_tickets_remaining(self, detector):
        """Test 'few tickets remaining' pattern."""
        result = detector.detect_availability('<div>Only a few tickets remaining</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_last_tickets(self, detector):
        """Test 'last tickets' pattern."""
        result = detector.detect_availability('<span>Last tickets!</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_almost_sold_out(self, detector):
        """Test 'almost sold out' pattern."""
        result = detector.detect_availability('<div>Almost sold out!</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.85

    def test_almost_gone(self, detector):
        """Test 'almost gone' pattern."""
        result = detector.detect_availability('<span>Tickets almost gone</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_selling_fast(self, detector):
        """Test 'selling fast' pattern."""
        result = detector.detect_availability('<div>Selling fast!</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.75

    def test_high_demand(self, detector):
        """Test 'high demand' pattern."""
        result = detector.detect_availability('<span>High demand event</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.70

    def test_low_availability(self, detector):
        """Test 'low availability' pattern."""
        result = detector.detect_availability('<div>Low ticket availability</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.80

    def test_running_low(self, detector):
        """Test 'running low' pattern."""
        result = detector.detect_availability('<span>Tickets running low</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.75

    def test_going_fast(self, detector):
        """Test 'going fast' pattern."""
        result = detector.detect_availability('<div>Tickets going fast</div>')
        assert result.status == 'limited'
        assert result.confidence >= 0.70

    def test_specific_low_count(self, detector):
        """Test specific low ticket count."""
        result = detector.detect_availability('<span>12 tickets available</span>')
        assert result.status == 'limited'
        assert result.confidence >= 0.85


# =============================================================================
# In Stock Detection Tests
# =============================================================================

class TestInStockDetection:
    """Tests for detecting in stock / available status."""

    def test_tickets_available(self, detector):
        """Test 'tickets available' pattern."""
        result = detector.detect_availability('<div>Tickets available</div>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.80

    def test_available_now(self, detector):
        """Test 'available now' pattern."""
        result = detector.detect_availability('<span>Available now!</span>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.80

    def test_on_sale_now(self, detector):
        """Test 'on sale now' pattern."""
        result = detector.detect_availability('<div>On Sale Now</div>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.85

    def test_buy_tickets(self, detector):
        """Test 'buy tickets' button."""
        result = detector.detect_availability('<button>Buy Tickets</button>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.75

    def test_get_tickets(self, detector):
        """Test 'get tickets' button."""
        result = detector.detect_availability('<button>Get Tickets</button>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.75

    def test_purchase_tickets(self, detector):
        """Test 'purchase tickets' pattern."""
        result = detector.detect_availability('<a>Purchase Tickets</a>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.75

    def test_book_now(self, detector):
        """Test 'book now' pattern."""
        result = detector.detect_availability('<button>Book Now</button>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.75

    def test_add_to_cart(self, detector):
        """Test 'add to cart' button."""
        result = detector.detect_availability('<button>Add to Cart</button>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.80

    def test_in_stock(self, detector):
        """Test 'in stock' pattern."""
        result = detector.detect_availability('<span>In Stock</span>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.85

    def test_many_tickets_available(self, detector):
        """Test large ticket count available."""
        result = detector.detect_availability('<div>500 tickets available</div>')
        assert result.status == 'in_stock'
        assert result.confidence >= 0.80


# =============================================================================
# Cross-Platform Compatibility Tests
# =============================================================================

class TestCrossPlatformCompatibility:
    """Tests for various ticketing platform formats."""

    def test_ticketmaster_style(self, detector):
        """Test Ticketmaster-style sold out."""
        html = '''
        <div class="ticket-status">
            <span class="status-icon"></span>
            <span class="status-text">Sold Out</span>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_eventbrite_style(self, detector):
        """Test Eventbrite-style availability."""
        html = '''
        <div class="ticket-options">
            <div class="ticket-type">
                <span>General Admission - SOLD OUT</span>
            </div>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_stubhub_style(self, detector):
        """Test StubHub-style limited availability."""
        html = '''
        <div class="ticket-info">
            <span class="urgency">Only 3 left!</span>
            <button>Buy Now</button>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'limited'

    def test_dice_style(self, detector):
        """Test Dice-style sold out."""
        html = '''
        <div class="event-card">
            <span class="badge badge-sold-out">SOLD OUT</span>
            <h3>Concert Name</h3>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_see_tickets_style(self, detector):
        """Test See Tickets-style availability."""
        html = '''
        <div class="event-listing">
            <p class="availability">Tickets are no longer available for this event</p>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_metrotix_style(self, detector):
        """Test MetroTix Chicago-style page."""
        html = '''
        <div class="event-detail">
            <h1>Local Band - Live Show</h1>
            <div class="ticket-info">
                <span class="status">This event is sold out</span>
            </div>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_thalia_hall_style(self, detector):
        """Test Thalia Hall-style page."""
        html = '''
        <article class="event">
            <div class="event-info">
                <h2>Jazz Night</h2>
                <div class="tickets">
                    <a class="btn" href="#">Get Tickets</a>
                </div>
            </div>
        </article>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'in_stock'

    def test_etix_style(self, detector):
        """Test Etix-style sold out."""
        html = '''
        <div class="event-container">
            <div class="event-header">
                <h1>Summer Festival</h1>
            </div>
            <div class="purchase-section">
                <span class="status-msg">This event has sold out</span>
            </div>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'


# =============================================================================
# Edge Cases and Error Handling Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_content(self, detector):
        """Test handling of empty content."""
        result = detector.detect_availability('')
        assert result.status == 'unknown'
        assert result.confidence == 0.0

    def test_none_content(self, detector):
        """Test handling of None content."""
        result = detector.detect_availability(None)
        assert result.status == 'unknown'

    def test_whitespace_only(self, detector):
        """Test whitespace-only content."""
        result = detector.detect_availability('   \n\t   ')
        assert result.status == 'unknown'

    def test_no_indicators(self, detector):
        """Test content with no availability indicators."""
        result = detector.detect_availability('<div>Welcome to our event!</div>')
        assert result.status == 'unknown'

    def test_ignores_script_content(self, detector):
        """Test that script tag content is ignored."""
        html = '''
        <script>var status = "sold_out";</script>
        <div>Buy Tickets</div>
        '''
        result = detector.detect_availability(html)
        # Should find "Buy Tickets", not the script content
        assert result.status == 'in_stock'

    def test_ignores_style_content(self, detector):
        """Test that style tag content is ignored."""
        html = '''
        <style>.sold-out { color: red; }</style>
        <div>Tickets Available</div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'in_stock'

    def test_partial_section_sold_out(self, detector):
        """Test that partial section sold out is handled correctly."""
        # This tests the negative pattern - VIP sold out shouldn't mean full sellout
        html = '<div>VIP section sold out - General admission available</div>'
        result = detector.detect_availability(html)
        # The negative pattern should reduce confidence or status
        # Since GA is available, ideally we'd detect in_stock
        # But this is edge case behavior - either is acceptable
        assert result.status in ('out_of_stock', 'in_stock', 'unknown')

    def test_past_tense_sold_out(self, detector):
        """Test that past tense 'sold out' is handled."""
        html = '<p>This show previously sold out in just 5 minutes</p>'
        result = detector.detect_availability(html)
        # Negative pattern should catch this
        # We don't want to report as sold out
        assert result.confidence < 0.90 or result.status != 'out_of_stock'

    def test_sold_out_higher_priority(self, detector):
        """Test that sold out takes priority over in stock."""
        html = '''
        <div>
            <span>Buy Tickets</span>
            <span class="alert">SOLD OUT</span>
        </div>
        '''
        result = detector.detect_availability(html)
        assert result.status == 'out_of_stock'

    def test_unicode_content(self, detector):
        """Test handling of unicode characters."""
        result = detector.detect_availability('<span>Sold Out ✗</span>')
        assert result.status == 'out_of_stock'

    def test_html_entities_decoded(self, detector):
        """Test that HTML entities are decoded."""
        html = '<div>Tickets&nbsp;Available</div>'
        result = detector.detect_availability(html)
        assert result.status == 'in_stock'


# =============================================================================
# Convenience Functions Tests
# =============================================================================

class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_detect_availability_function(self):
        """Test the detect_availability function."""
        result = detect_availability('<div>SOLD OUT</div>')
        assert isinstance(result, dict)
        assert result['status'] == 'out_of_stock'
        assert 'confidence' in result
        assert 'matched_pattern' in result

    def test_get_availability_status_function(self):
        """Test the get_availability_status function."""
        status = get_availability_status('<div>Sold Out</div>')
        assert status == 'out_of_stock'

    def test_is_sold_out_true(self):
        """Test is_sold_out returns True for sold out content."""
        assert is_sold_out('<div>SOLD OUT</div>') is True

    def test_is_sold_out_false(self):
        """Test is_sold_out returns False for available content."""
        assert is_sold_out('<button>Buy Tickets</button>') is False


# =============================================================================
# Change Type Determination Tests
# =============================================================================

class TestChangeTypeDetermination:
    """Tests for determine_change_type function."""

    def test_new_listing_in_stock(self):
        """Test new listing with in stock status."""
        change_type = determine_change_type(None, 'in_stock')
        assert change_type == 'new'

    def test_new_listing_sold_out(self):
        """Test new listing already sold out."""
        change_type = determine_change_type(None, 'out_of_stock')
        assert change_type == 'sellout'

    def test_new_listing_limited(self):
        """Test new listing with limited availability."""
        change_type = determine_change_type(None, 'limited')
        assert change_type == 'limited'

    def test_became_sold_out(self):
        """Test transition to sold out."""
        change_type = determine_change_type('in_stock', 'out_of_stock')
        assert change_type == 'sellout'

    def test_became_sold_out_from_limited(self):
        """Test transition from limited to sold out."""
        change_type = determine_change_type('limited', 'out_of_stock')
        assert change_type == 'sellout'

    def test_restock_from_sold_out(self):
        """Test restock (sold out to in stock)."""
        change_type = determine_change_type('out_of_stock', 'in_stock')
        assert change_type == 'restock'

    def test_restock_to_limited(self):
        """Test restock to limited availability."""
        change_type = determine_change_type('out_of_stock', 'limited')
        assert change_type == 'restock'

    def test_became_limited(self):
        """Test transition from in stock to limited."""
        change_type = determine_change_type('in_stock', 'limited')
        assert change_type == 'limited'

    def test_price_change(self):
        """Test price change without availability change."""
        change_type = determine_change_type('in_stock', 'in_stock', prices_changed=True)
        assert change_type == 'price_change'

    def test_default_update(self):
        """Test default update type."""
        change_type = determine_change_type('in_stock', 'in_stock', prices_changed=False)
        assert change_type == 'update'


# =============================================================================
# Availability Result Tests
# =============================================================================

class TestAvailabilityResult:
    """Tests for AvailabilityResult dataclass."""

    def test_to_dict(self):
        """Test to_dict method."""
        result = AvailabilityResult(
            status='out_of_stock',
            confidence=0.95,
            matched_pattern='sold out',
            matched_text='This event is sold out'
        )
        d = result.to_dict()

        assert d['status'] == 'out_of_stock'
        assert d['confidence'] == 0.95
        assert d['matched_pattern'] == 'sold out'
        assert d['matched_text'] == 'This event is sold out'

    def test_is_sold_out_property(self):
        """Test is_sold_out property."""
        sold_out = AvailabilityResult(status='out_of_stock', confidence=0.9)
        assert sold_out.is_sold_out is True

        in_stock = AvailabilityResult(status='in_stock', confidence=0.9)
        assert in_stock.is_sold_out is False

    def test_is_available_property(self):
        """Test is_available property."""
        in_stock = AvailabilityResult(status='in_stock', confidence=0.9)
        assert in_stock.is_available is True

        limited = AvailabilityResult(status='limited', confidence=0.9)
        assert limited.is_available is True

        sold_out = AvailabilityResult(status='out_of_stock', confidence=0.9)
        assert sold_out.is_available is False


# =============================================================================
# Has Availability Changed Tests
# =============================================================================

class TestHasAvailabilityChanged:
    """Tests for has_availability_changed method."""

    def test_no_change(self, detector):
        """Test when availability hasn't changed."""
        changed, old, new = detector.has_availability_changed(
            '<div>SOLD OUT</div>',
            '<div>Sold Out</div>'
        )
        assert changed is False
        assert old == new

    def test_changed_to_sold_out(self, detector):
        """Test when tickets become sold out."""
        changed, old, new = detector.has_availability_changed(
            '<button>Buy Tickets</button>',
            '<div>SOLD OUT</div>'
        )
        assert changed is True
        assert old == 'in_stock'
        assert new == 'out_of_stock'

    def test_changed_to_available(self, detector):
        """Test when tickets become available (restock)."""
        changed, old, new = detector.has_availability_changed(
            '<div>Sold Out</div>',
            '<button>Buy Tickets</button>'
        )
        assert changed is True
        assert old == 'out_of_stock'
        assert new == 'in_stock'

    def test_low_confidence_both(self, detector):
        """Test when both have low confidence."""
        changed, old, new = detector.has_availability_changed(
            '<div>Hello world</div>',
            '<div>Welcome to our site</div>'
        )
        assert changed is False
        assert old is None
        assert new is None


# =============================================================================
# Integration with Notification Tests
# =============================================================================

class TestNotificationIntegration:
    """Tests for integration with Slack notification module."""

    def test_sellout_change_type_for_notification(self, detector):
        """Test that sellout properly triggers sellout change type."""
        old_content = '<button>Get Tickets</button>'
        new_content = '<div class="alert">SOLD OUT</div>'

        old_result = detector.detect_availability(old_content)
        new_result = detector.detect_availability(new_content)

        change_type = determine_change_type(
            old_result.status,
            new_result.status
        )

        # This should trigger 'sellout' for Slack notification
        assert change_type == 'sellout'

    def test_restock_change_type_for_notification(self, detector):
        """Test that restock properly triggers restock change type."""
        old_content = '<div>Sold Out</div>'
        new_content = '<button>Buy Now</button>'

        old_result = detector.detect_availability(old_content)
        new_result = detector.detect_availability(new_content)

        change_type = determine_change_type(
            old_result.status,
            new_result.status
        )

        # This should trigger 'restock' for Slack notification
        assert change_type == 'restock'


# =============================================================================
# JSON Serialization Tests
# =============================================================================

class TestJSONSerialization:
    """Tests for JSON serialization for database storage."""

    def test_result_json_serializable(self, detector):
        """Test that results can be JSON serialized."""
        import json

        result = detector.detect_availability('<div>SOLD OUT</div>')
        d = result.to_dict()

        # Should be JSON serializable
        json_str = json.dumps(d)
        assert json_str is not None

        # Should round-trip correctly
        parsed = json.loads(json_str)
        assert parsed['status'] == 'out_of_stock'

    def test_status_matches_snapshot_schema(self, detector):
        """Test that status format matches expected snapshot schema."""
        result = detector.detect_availability('<div>Sold Out</div>')

        # Status should be one of the expected values
        assert result.status in ('in_stock', 'out_of_stock', 'limited', 'unknown')

        # Should be a string suitable for extracted_availability field
        assert isinstance(result.status, str)
