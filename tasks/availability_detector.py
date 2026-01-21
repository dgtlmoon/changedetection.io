"""
Availability Detection Module for TicketWatch

This module provides utilities for detecting ticket availability states from HTML content.
Supports common sold out, unavailable, and limited availability patterns across ticketing platforms.

Features:
- Common sold out text pattern detection
- Limited availability detection
- In-stock/available detection
- Structured availability status output for storage in snapshots table

Usage:
    from tasks.availability_detector import AvailabilityDetector

    detector = AvailabilityDetector()
    status = detector.detect_availability(html_content)
    # Returns: {"status": "out_of_stock", "confidence": 0.9, "matched_pattern": "Sold Out"}
"""

import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

# Try to use loguru if available
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# Availability Status Enum
# =============================================================================

class AvailabilityStatus(Enum):
    """Possible availability statuses for tickets."""
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    LIMITED = "limited"
    UNKNOWN = "unknown"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class AvailabilityResult:
    """Represents the detected availability status."""
    status: str  # in_stock, out_of_stock, limited, unknown
    confidence: float = 0.0  # 0.0 to 1.0
    matched_pattern: str = ""
    matched_text: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @property
    def is_sold_out(self) -> bool:
        """Check if the status indicates sold out."""
        return self.status == AvailabilityStatus.OUT_OF_STOCK.value

    @property
    def is_available(self) -> bool:
        """Check if the status indicates tickets are available."""
        return self.status in (
            AvailabilityStatus.IN_STOCK.value,
            AvailabilityStatus.LIMITED.value
        )


# =============================================================================
# Pattern Definitions
# =============================================================================

class AvailabilityPatterns:
    """
    Regex patterns for detecting availability states.

    Covers common patterns from various ticketing platforms:
    - Ticketmaster, AXS, Eventbrite, StubHub
    - MetroTix, Thalia Hall, Etix, TicketWeb
    - Prekindle, See Tickets, Dice, etc.
    """

    # ==========================================================================
    # SOLD OUT / UNAVAILABLE Patterns (High Priority)
    # ==========================================================================

    # Primary sold out patterns - exact matches
    # NOTE: Order matters - more specific patterns should come first
    SOLD_OUT_PRIMARY: List[Tuple[re.Pattern, float]] = [
        # Explicit "Sold Out" variations (but NOT "almost sold out" - that's limited)
        (re.compile(r'(?<!\balmost\s)\bsold\s*out\b', re.IGNORECASE), 0.95),
        (re.compile(r'(?<!\balmost\s)\bsoldout\b', re.IGNORECASE), 0.95),

        # Explicit "Unavailable" variations
        (re.compile(r'\bunavailable\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bnot\s+available\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bno\s+longer\s+available\b', re.IGNORECASE), 0.95),

        # Out of stock variations
        (re.compile(r'\bout\s+of\s+stock\b', re.IGNORECASE), 0.95),
        (re.compile(r'\bout\-of\-stock\b', re.IGNORECASE), 0.95),

        # Event-specific sold out
        (re.compile(r'\bevent\s+is\s+sold\s+out\b', re.IGNORECASE), 0.98),
        (re.compile(r'\bshow\s+is\s+sold\s+out\b', re.IGNORECASE), 0.98),
        (re.compile(r'\bconcert\s+is\s+sold\s+out\b', re.IGNORECASE), 0.98),
        (re.compile(r'\btickets\s+sold\s+out\b', re.IGNORECASE), 0.98),

        # No tickets variations
        (re.compile(r'\bno\s+tickets\s+available\b', re.IGNORECASE), 0.95),
        (re.compile(r'\bno\s+tickets\s+remaining\b', re.IGNORECASE), 0.95),
        (re.compile(r'\bno\s+tickets\s+left\b', re.IGNORECASE), 0.95),
        (re.compile(r'\bzero\s+tickets\b', re.IGNORECASE), 0.90),
        (re.compile(r'\b0\s+tickets\s+(?:available|remaining|left)\b', re.IGNORECASE), 0.95),

        # Off sale variations
        (re.compile(r'\boff\s*sale\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bsale\s+ended\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bsales\s+ended\b', re.IGNORECASE), 0.90),

        # Cancelled/postponed (also no tickets available)
        (re.compile(r'\bcancell?ed\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bpostponed\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bevent\s+cancelled\b', re.IGNORECASE), 0.95),
    ]

    # Secondary sold out patterns - context dependent
    SOLD_OUT_SECONDARY: List[Tuple[re.Pattern, float]] = [
        # Capacity messages
        (re.compile(r'\bat\s+capacity\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bfull\s+capacity\b', re.IGNORECASE), 0.85),

        # Waitlist indicators
        (re.compile(r'\bjoin\s+(?:the\s+)?waitlist\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bwaitlist\s+available\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bnotify\s+(?:me|when)\b', re.IGNORECASE), 0.70),

        # Check back messages
        (re.compile(r'\bcheck\s+back\s+(?:soon|later)\b', re.IGNORECASE), 0.75),
        (re.compile(r'\bmore\s+tickets\s+may\s+become\s+available\b', re.IGNORECASE), 0.80),
    ]

    # ==========================================================================
    # LIMITED AVAILABILITY Patterns
    # ==========================================================================

    LIMITED_PATTERNS: List[Tuple[re.Pattern, float]] = [
        # Limited quantity
        (re.compile(r'\blimited\s+(?:tickets?|availability|quantity)\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bonly\s+\d+\s+(?:tickets?|left|remaining|available)\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bjust\s+\d+\s+(?:tickets?|left|remaining)\b', re.IGNORECASE), 0.90),
        (re.compile(r'\b(?:few|last)\s+(?:tickets?|remaining)\b', re.IGNORECASE), 0.85),
        (re.compile(r'\balmost\s+sold\s+out\b', re.IGNORECASE), 0.90),
        (re.compile(r'\balmost\s+gone\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bselling\s+fast\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bhigh\s+demand\b', re.IGNORECASE), 0.75),
        (re.compile(r'\blow\s+(?:ticket\s+)?availability\b', re.IGNORECASE), 0.85),
        (re.compile(r'\brunning\s+low\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bgoing\s+fast\b', re.IGNORECASE), 0.75),
        (re.compile(r'\bhurry\b', re.IGNORECASE), 0.70),
        (re.compile(r'\bact\s+fast\b', re.IGNORECASE), 0.70),
        (re.compile(r'\bdon\'?t\s+miss\s+out\b', re.IGNORECASE), 0.65),

        # Specific remaining counts (low numbers indicate limited)
        (re.compile(r'\b([1-9]|1[0-9]|20)\s+tickets?\s+(?:left|remaining|available)\b', re.IGNORECASE), 0.90),
    ]

    # ==========================================================================
    # IN STOCK / AVAILABLE Patterns
    # ==========================================================================

    IN_STOCK_PATTERNS: List[Tuple[re.Pattern, float]] = [
        # Explicit availability
        (re.compile(r'\btickets?\s+available\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bavailable\s+now\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bon\s+sale\s+now\b', re.IGNORECASE), 0.90),
        (re.compile(r'\bbuy\s+tickets?\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bbuy\s+now\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bget\s+tickets?\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bpurchase\s+tickets?\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bpurchase\s+now\b', re.IGNORECASE), 0.80),
        (re.compile(r'\bbook\s+(?:now|tickets?)\b', re.IGNORECASE), 0.80),
        (re.compile(r'\badd\s+to\s+cart\b', re.IGNORECASE), 0.85),
        (re.compile(r'\bin\s+stock\b', re.IGNORECASE), 0.90),

        # Quantity available (larger numbers)
        (re.compile(r'\b\d{2,}\s+tickets?\s+available\b', re.IGNORECASE), 0.85),
    ]

    # ==========================================================================
    # Negative Patterns (to avoid false positives)
    # ==========================================================================

    NEGATIVE_PATTERNS: List[re.Pattern] = [
        # Avoid matching "sold out" in past tense news
        re.compile(r'was\s+sold\s+out', re.IGNORECASE),
        re.compile(r'sold\s+out\s+(?:in|within)\s+\d+\s+(?:minutes?|hours?|days?)', re.IGNORECASE),
        re.compile(r'previously\s+sold\s+out', re.IGNORECASE),

        # Avoid matching section-specific sold out
        re.compile(r'(?:vip|premium|floor)\s+(?:section\s+)?sold\s+out', re.IGNORECASE),

        # Avoid matching in script tags or JSON
        re.compile(r'"sold_out"\s*:', re.IGNORECASE),
        re.compile(r'"status"\s*:\s*"sold_out"', re.IGNORECASE),
    ]


# =============================================================================
# Availability Detector Implementation
# =============================================================================

class AvailabilityDetector:
    """
    Detects ticket availability status from HTML or text content.

    This class provides methods for:
    - Detecting sold out status
    - Detecting limited availability
    - Detecting in-stock status
    - Combining results with confidence scoring

    Example:
        detector = AvailabilityDetector()
        result = detector.detect_availability(html_content)
        # result = AvailabilityResult(
        #     status="out_of_stock",
        #     confidence=0.95,
        #     matched_pattern="sold out",
        #     matched_text="This event is sold out"
        # )
    """

    def __init__(self):
        """Initialize the availability detector."""
        pass

    def detect_availability(self, content: str) -> AvailabilityResult:
        """
        Detect the availability status from content.

        Args:
            content: HTML or text content to analyze.

        Returns:
            AvailabilityResult with status, confidence, and matched pattern.
        """
        if not content:
            return AvailabilityResult(
                status=AvailabilityStatus.UNKNOWN.value,
                confidence=0.0,
                matched_pattern="",
                matched_text=""
            )

        # Clean HTML tags but preserve text
        text = self._strip_html(content)

        # Check for sold out patterns first (highest priority)
        sold_out_result = self._check_sold_out(text)
        if sold_out_result and sold_out_result.confidence >= 0.80:
            return sold_out_result

        # Check for limited availability
        limited_result = self._check_limited(text)
        if limited_result and limited_result.confidence >= 0.75:
            return limited_result

        # Check for in stock / available
        in_stock_result = self._check_in_stock(text)
        if in_stock_result and in_stock_result.confidence >= 0.75:
            return in_stock_result

        # If we found a lower confidence sold out, return it
        if sold_out_result and sold_out_result.confidence >= 0.70:
            return sold_out_result

        # Default to unknown
        return AvailabilityResult(
            status=AvailabilityStatus.UNKNOWN.value,
            confidence=0.0,
            matched_pattern="",
            matched_text=""
        )

    def detect_status_string(self, content: str) -> str:
        """
        Detect availability and return just the status string.

        Args:
            content: HTML or text content.

        Returns:
            Status string: "in_stock", "out_of_stock", "limited", or "unknown"
        """
        result = self.detect_availability(content)
        return result.status

    def is_sold_out(self, content: str) -> bool:
        """
        Check if the content indicates a sold out status.

        Args:
            content: HTML or text content.

        Returns:
            True if sold out is detected with sufficient confidence.
        """
        result = self.detect_availability(content)
        return result.status == AvailabilityStatus.OUT_OF_STOCK.value

    def has_availability_changed(
        self,
        old_content: str,
        new_content: str
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Check if availability status has changed between two content snapshots.

        Args:
            old_content: Previous HTML/text content.
            new_content: Current HTML/text content.

        Returns:
            Tuple of (changed, old_status, new_status)
        """
        old_result = self.detect_availability(old_content)
        new_result = self.detect_availability(new_content)

        # Consider it changed only if both have reasonable confidence
        if old_result.confidence < 0.5 and new_result.confidence < 0.5:
            return (False, None, None)

        changed = old_result.status != new_result.status
        return (changed, old_result.status, new_result.status)

    def _check_sold_out(self, text: str) -> Optional[AvailabilityResult]:
        """Check for sold out patterns."""
        best_match = None
        best_confidence = 0.0

        # Check primary patterns
        for pattern, confidence in AvailabilityPatterns.SOLD_OUT_PRIMARY:
            match = pattern.search(text)
            if match:
                # Check if this is a negative pattern (false positive)
                if self._is_negative_match(text, match):
                    continue

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = AvailabilityResult(
                        status=AvailabilityStatus.OUT_OF_STOCK.value,
                        confidence=confidence,
                        matched_pattern=pattern.pattern,
                        matched_text=self._get_context(text, match)
                    )

        # Check secondary patterns only if no primary match
        if best_confidence < 0.80:
            for pattern, confidence in AvailabilityPatterns.SOLD_OUT_SECONDARY:
                match = pattern.search(text)
                if match:
                    if self._is_negative_match(text, match):
                        continue

                    if confidence > best_confidence:
                        best_confidence = confidence
                        best_match = AvailabilityResult(
                            status=AvailabilityStatus.OUT_OF_STOCK.value,
                            confidence=confidence,
                            matched_pattern=pattern.pattern,
                            matched_text=self._get_context(text, match)
                        )

        return best_match

    def _check_limited(self, text: str) -> Optional[AvailabilityResult]:
        """Check for limited availability patterns."""
        best_match = None
        best_confidence = 0.0

        for pattern, confidence in AvailabilityPatterns.LIMITED_PATTERNS:
            match = pattern.search(text)
            if match:
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = AvailabilityResult(
                        status=AvailabilityStatus.LIMITED.value,
                        confidence=confidence,
                        matched_pattern=pattern.pattern,
                        matched_text=self._get_context(text, match)
                    )

        return best_match

    def _check_in_stock(self, text: str) -> Optional[AvailabilityResult]:
        """Check for in stock / available patterns."""
        best_match = None
        best_confidence = 0.0

        for pattern, confidence in AvailabilityPatterns.IN_STOCK_PATTERNS:
            match = pattern.search(text)
            if match:
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = AvailabilityResult(
                        status=AvailabilityStatus.IN_STOCK.value,
                        confidence=confidence,
                        matched_pattern=pattern.pattern,
                        matched_text=self._get_context(text, match)
                    )

        return best_match

    def _is_negative_match(self, text: str, match: re.Match) -> bool:
        """Check if the match is a false positive based on negative patterns."""
        # Get surrounding context
        start = max(0, match.start() - 50)
        end = min(len(text), match.end() + 50)
        context = text[start:end]

        # Check against negative patterns
        for neg_pattern in AvailabilityPatterns.NEGATIVE_PATTERNS:
            if neg_pattern.search(context):
                return True

        return False

    def _get_context(self, text: str, match: re.Match, context_chars: int = 50) -> str:
        """Get surrounding context for a match."""
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        context = text[start:end].strip()

        # Add ellipsis if truncated
        if start > 0:
            context = "..." + context
        if end < len(text):
            context = context + "..."

        return context

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

def detect_availability(content: str) -> Dict[str, Any]:
    """
    Detect availability status from content.

    Convenience function for quick availability detection.

    Args:
        content: HTML or text content.

    Returns:
        Dictionary with status, confidence, matched_pattern, matched_text.

    Example:
        >>> result = detect_availability('<div class="alert">SOLD OUT</div>')
        >>> result
        {'status': 'out_of_stock', 'confidence': 0.95, ...}
    """
    detector = AvailabilityDetector()
    result = detector.detect_availability(content)
    return result.to_dict()


def get_availability_status(content: str) -> str:
    """
    Get just the availability status string.

    Args:
        content: HTML or text content.

    Returns:
        Status string: "in_stock", "out_of_stock", "limited", or "unknown"
    """
    detector = AvailabilityDetector()
    return detector.detect_status_string(content)


def is_sold_out(content: str) -> bool:
    """
    Check if content indicates sold out.

    Args:
        content: HTML or text content.

    Returns:
        True if sold out detected.
    """
    detector = AvailabilityDetector()
    return detector.is_sold_out(content)


def determine_change_type(
    old_availability: Optional[str],
    new_availability: str,
    prices_changed: bool = False
) -> str:
    """
    Determine the notification change type based on availability changes.

    Args:
        old_availability: Previous availability status (or None for new listings).
        new_availability: Current availability status.
        prices_changed: Whether prices have also changed.

    Returns:
        Change type string for notification: "new", "sellout", "restock",
        "limited", "price_change", or "update".
    """
    # New listing
    if old_availability is None:
        if new_availability == AvailabilityStatus.OUT_OF_STOCK.value:
            return "sellout"
        elif new_availability == AvailabilityStatus.LIMITED.value:
            return "limited"
        return "new"

    # Became sold out
    if (new_availability == AvailabilityStatus.OUT_OF_STOCK.value and
            old_availability != AvailabilityStatus.OUT_OF_STOCK.value):
        return "sellout"

    # Back in stock (restock)
    if (old_availability == AvailabilityStatus.OUT_OF_STOCK.value and
            new_availability in (AvailabilityStatus.IN_STOCK.value, AvailabilityStatus.LIMITED.value)):
        return "restock"

    # Became limited
    if (new_availability == AvailabilityStatus.LIMITED.value and
            old_availability == AvailabilityStatus.IN_STOCK.value):
        return "limited"

    # Price change
    if prices_changed:
        return "price_change"

    # Default update
    return "update"


# =============================================================================
# CLI Testing
# =============================================================================

if __name__ == "__main__":
    # Test examples
    test_cases = [
        # Sold out cases
        '<div class="status">SOLD OUT</div>',
        '<span>This event is sold out</span>',
        '<p>Tickets are no longer available</p>',
        '<div>Out of stock</div>',
        '<span class="alert">No tickets remaining</span>',
        '<p>Sales ended</p>',

        # Limited availability
        '<span>Only 5 tickets left!</span>',
        '<div>Limited availability</div>',
        '<p>Selling fast - act now!</p>',
        '<span>Almost sold out</span>',

        # In stock
        '<button>Buy Tickets</button>',
        '<div>Tickets available now</div>',
        '<span>On sale now</span>',
        '<button class="purchase">Add to Cart</button>',

        # Complex/ambiguous
        '<div>VIP section sold out - General admission available</div>',
        '<p>This show previously sold out in 5 minutes</p>',
        '<script>var status = "sold_out";</script><div>Buy Now</div>',
    ]

    detector = AvailabilityDetector()

    print("Availability Detection Test Results")
    print("=" * 70)

    for i, test in enumerate(test_cases, 1):
        result = detector.detect_availability(test)
        print(f"\nTest {i}:")
        print(f"  Input: {test[:60]}...")
        print(f"  Status: {result.status}")
        print(f"  Confidence: {result.confidence:.2f}")
        if result.matched_text:
            print(f"  Matched: {result.matched_text[:50]}")
