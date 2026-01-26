#!/usr/bin/env python3
"""
Unit tests for watch words processor logic (block_words and trigger_words).

These tests directly test the RuleEngine methods without requiring
the full test framework infrastructure.
"""
import pytest


def test_evaluate_block_words_basic():
    """
    Test: evaluate_block_words blocks when words are present.

    block_words semantics: "Notify when these words DISAPPEAR"
    - Returns True (blocked) while words ARE present on page
    - Returns False (allowed) when words are NOT present
    """
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content_with_sold_out = """
    Concert Tickets
    Sold Out
    Check back later for availability.
    """

    content_without_sold_out = """
    Concert Tickets
    Available
    Buy now before they are gone!
    """

    patterns = ["Sold Out"]

    # Should be BLOCKED (True) when "Sold Out" IS present
    assert RuleEngine.evaluate_block_words(content_with_sold_out, patterns) == True

    # Should be ALLOWED (False) when "Sold Out" is NOT present
    assert RuleEngine.evaluate_block_words(content_without_sold_out, patterns) == False


def test_evaluate_block_words_empty_patterns():
    """Test: Empty patterns should not block."""
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content = "Some text"

    # Empty patterns should return False (no blocking)
    assert RuleEngine.evaluate_block_words(content, []) == False
    assert RuleEngine.evaluate_block_words(content, None) == False


def test_evaluate_block_words_case_insensitive():
    """Test: Plain text matching is case-insensitive."""
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content = "SOLD OUT - Tickets Not Available"

    # Lowercase pattern should match uppercase content
    assert RuleEngine.evaluate_block_words(content, ["sold out"]) == True

    # Mixed case patterns should also work
    assert RuleEngine.evaluate_block_words(content, ["SoLd OuT"]) == True


def test_evaluate_block_words_regex():
    """Test: Perl-style regex patterns work."""
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content = "Sold Out - Not Available"

    # Regex pattern should match
    assert RuleEngine.evaluate_block_words(content, ["/sold\\s*out/i"]) == True

    # Regex that doesn't match should allow
    assert RuleEngine.evaluate_block_words(content, ["/buy\\s*now/i"]) == False


def test_evaluate_trigger_words_basic():
    """
    Test: evaluate_trigger_words blocks until words appear.

    trigger_words semantics: "Notify when these words APPEAR"
    - Returns True (blocked) while words are NOT present on page
    - Returns False (allowed) when words ARE present
    """
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content_with_on_sale = """
    Concert Tickets
    On Sale Now
    Get your tickets today!
    """

    content_without_on_sale = """
    Concert Tickets
    Coming Soon
    Sales begin January 15th.
    """

    patterns = ["On Sale Now"]

    # Should be ALLOWED (False) when "On Sale Now" IS present
    assert RuleEngine.evaluate_trigger_words(content_with_on_sale, patterns) == False

    # Should be BLOCKED (True) when "On Sale Now" is NOT present
    assert RuleEngine.evaluate_trigger_words(content_without_on_sale, patterns) == True


def test_evaluate_trigger_words_empty_patterns():
    """Test: Empty patterns should not block."""
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content = "Some text"

    # Empty patterns should return False (no blocking)
    assert RuleEngine.evaluate_trigger_words(content, []) == False
    assert RuleEngine.evaluate_trigger_words(content, None) == False


def test_evaluate_trigger_words_multiple_patterns():
    """Test: Any matching pattern allows notification."""
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    content_with_buy = """
    Concert Tickets
    Buy Now
    Get your tickets!
    """

    content_with_none = """
    Concert Tickets
    Coming Soon
    Check back later.
    """

    patterns = ["On Sale Now", "Buy Now", "Available"]

    # Should be ALLOWED (False) when ANY pattern matches
    assert RuleEngine.evaluate_trigger_words(content_with_buy, patterns) == False

    # Should be BLOCKED (True) when NO pattern matches
    assert RuleEngine.evaluate_trigger_words(content_with_none, patterns) == True


def test_filter_config_block_words_property():
    """Test: FilterConfig.block_words property returns merged rules."""
    from changedetectionio.processors.text_json_diff.processor import FilterConfig
    from unittest.mock import MagicMock

    # Create mock watch and datastore
    mock_watch = MagicMock()
    mock_watch.get.return_value = ["Sold Out"]
    mock_watch.__getitem__ = mock_watch.get

    mock_datastore = MagicMock()
    mock_datastore.get_tag_overrides_for_watch.return_value = []

    filter_config = FilterConfig(mock_watch, mock_datastore)

    # Should return the block_words from watch
    result = filter_config.block_words
    assert result == ["Sold Out"]


def test_filter_config_trigger_words_property():
    """Test: FilterConfig.trigger_words property returns merged rules."""
    from changedetectionio.processors.text_json_diff.processor import FilterConfig
    from unittest.mock import MagicMock

    # Create mock watch and datastore
    mock_watch = MagicMock()
    mock_watch.get.return_value = ["On Sale Now"]
    mock_watch.__getitem__ = mock_watch.get

    mock_datastore = MagicMock()
    mock_datastore.get_tag_overrides_for_watch.return_value = []

    filter_config = FilterConfig(mock_watch, mock_datastore)

    # Should return the trigger_words from watch
    result = filter_config.trigger_words
    assert result == ["On Sale Now"]


def test_combined_block_and_trigger_words():
    """
    Test: Both rules must pass for notification to be allowed.

    Combined scenario:
    - block_words: "Sold Out" (notify when it disappears)
    - trigger_words: "Available" (notify when it appears)

    Notification allowed when:
    - "Sold Out" is NOT present (block_words returns False)
    - "Available" IS present (trigger_words returns False)
    """
    from changedetectionio.processors.text_json_diff.processor import RuleEngine

    # Content has "Sold Out" but not "Available"
    content_sold_out = """
    Sold Out
    Check back later.
    """

    # Content has both - still blocked by block_words
    content_both = """
    Sold Out
    Available
    """

    # Content has only "Available" - should allow notification
    content_available = """
    Available
    Get your tickets now!
    """

    block_patterns = ["Sold Out"]
    trigger_patterns = ["Available"]

    # Scenario 1: Has "Sold Out", no "Available" → blocked by BOTH
    assert RuleEngine.evaluate_block_words(content_sold_out, block_patterns) == True  # Blocked
    assert RuleEngine.evaluate_trigger_words(content_sold_out, trigger_patterns) == True  # Blocked

    # Scenario 2: Has both → blocked by block_words
    assert RuleEngine.evaluate_block_words(content_both, block_patterns) == True  # Blocked
    assert RuleEngine.evaluate_trigger_words(content_both, trigger_patterns) == False  # Allowed

    # Scenario 3: Only "Available" → both rules pass (notification allowed)
    assert RuleEngine.evaluate_block_words(content_available, block_patterns) == False  # Allowed
    assert RuleEngine.evaluate_trigger_words(content_available, trigger_patterns) == False  # Allowed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
