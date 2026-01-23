"""
Base classes and interfaces for LLM extraction providers.

This module defines the abstract base class that all LLM providers must implement,
along with common data structures for extraction results and cost tracking.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================


class LLMExtractionError(Exception):
    """Base exception for LLM extraction errors."""
    pass


class LLMProviderError(LLMExtractionError):
    """Error communicating with the LLM provider."""
    pass


class LLMRateLimitError(LLMExtractionError):
    """Rate limit exceeded for the LLM provider."""
    pass


class LLMAuthenticationError(LLMExtractionError):
    """Authentication failed with the LLM provider."""
    pass


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class LLMExtractionResult:
    """Result of LLM-based extraction including cost tracking."""

    # Extracted event fields
    event_name: str | None = None
    artist: str | None = None
    venue: str | None = None
    event_date: date | None = None
    event_time: time | None = None
    price_low: Decimal | None = None
    price_high: Decimal | None = None
    is_sold_out: bool = False

    # Metadata
    success: bool = False
    error: str | None = None
    raw_response: str | None = None

    # Cost tracking
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal('0'))

    # Provider info
    provider: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for database storage."""
        return {
            'event_name': self.event_name,
            'artist': self.artist,
            'venue': self.venue,
            'event_date': self.event_date.isoformat() if self.event_date else None,
            'event_time': self.event_time.isoformat() if self.event_time else None,
            'price_low': float(self.price_low) if self.price_low else None,
            'price_high': float(self.price_high) if self.price_high else None,
            'is_sold_out': self.is_sold_out,
        }

    def to_extraction_result(self):
        """Convert to ExtractionResult for compatibility with CSS-based extraction."""
        from tasks.event_extractor import ExtractionResult

        return ExtractionResult(
            event_name=self.event_name,
            artist=self.artist,
            venue=self.venue,
            event_date=self.event_date,
            event_time=self.event_time,
            current_price_low=self.price_low,
            current_price_high=self.price_high,
            is_sold_out=self.is_sold_out,
        )


@dataclass
class LLMCostRecord:
    """Record of an LLM API call for cost tracking."""

    timestamp: datetime = field(default_factory=datetime.utcnow)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal('0'))
    watch_uuid: str | None = None
    success: bool = False
    error: str | None = None


# =============================================================================
# Default Prompt Template
# =============================================================================


DEFAULT_EXTRACTION_PROMPT = """Extract event information from the following HTML content. Return a JSON object with these fields:

- event_name: The name/title of the event (string or null)
- artist: The performing artist or band name (string or null)
- venue: The venue name (string or null)
- event_date: The event date in YYYY-MM-DD format (string or null)
- event_time: The event start time in HH:MM format, 24-hour (string or null)
- price_low: The lowest ticket price as a number (number or null)
- price_high: The highest ticket price as a number (number or null)
- is_sold_out: Whether tickets are sold out (boolean)

Only return the JSON object, no other text. If a field cannot be determined, use null.

HTML Content:
{html_content}
"""


# =============================================================================
# Abstract Base Class
# =============================================================================


class LLMExtractor(ABC):
    """
    Abstract base class for LLM extraction providers.

    All LLM providers (OpenAI, Anthropic, Ollama) must implement this interface
    to ensure consistent behavior and cost tracking.
    """

    # Provider identification
    provider_name: str = "base"
    default_model: str = ""

    # Cost per 1M tokens (to be set by subclasses)
    input_cost_per_million: Decimal = Decimal('0')
    output_cost_per_million: Decimal = Decimal('0')

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout: int = 30,
    ):
        """
        Initialize the LLM extractor.

        Args:
            api_key: API key for the provider (not needed for Ollama)
            model: Model to use (defaults to provider's default)
            api_base_url: Custom API base URL (for self-hosted or proxies)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.model = model or self.default_model
        self.api_base_url = api_base_url
        self.timeout = timeout

    @abstractmethod
    def is_configured(self) -> bool:
        """
        Check if the provider is properly configured.

        Returns:
            True if the provider has all required configuration
        """
        pass

    @abstractmethod
    async def extract(
        self,
        html_content: str,
        prompt_template: str | None = None,
    ) -> LLMExtractionResult:
        """
        Extract event data from HTML content using the LLM.

        Args:
            html_content: Raw HTML content to analyze
            prompt_template: Custom prompt template (uses default if not provided)

        Returns:
            LLMExtractionResult with extracted data and cost info
        """
        pass

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """
        Calculate the cost of an API call based on token usage.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD as a Decimal
        """
        input_cost = (Decimal(input_tokens) / Decimal('1000000')) * self.input_cost_per_million
        output_cost = (Decimal(output_tokens) / Decimal('1000000')) * self.output_cost_per_million
        return input_cost + output_cost

    def _parse_json_response(self, response_text: str) -> dict[str, Any]:
        """
        Parse JSON from LLM response, handling common formatting issues.

        Args:
            response_text: Raw response text from the LLM

        Returns:
            Parsed dictionary
        """
        # Try direct JSON parsing first
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in the response
        json_match = re.search(r'\{[\s\S]*\}', response_text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from response: {response_text[:200]}")

    def _convert_result(self, data: dict[str, Any]) -> LLMExtractionResult:
        """
        Convert parsed JSON data to LLMExtractionResult.

        Args:
            data: Parsed JSON dictionary from LLM response

        Returns:
            LLMExtractionResult with converted values
        """
        result = LLMExtractionResult(
            success=True,
            provider=self.provider_name,
            model=self.model,
        )

        # Extract text fields
        result.event_name = data.get('event_name')
        result.artist = data.get('artist')
        result.venue = data.get('venue')

        # Parse date
        date_str = data.get('event_date')
        if date_str:
            try:
                result.event_date = date.fromisoformat(date_str)
            except (ValueError, TypeError):
                logger.warning(f"Could not parse event_date: {date_str}")

        # Parse time
        time_str = data.get('event_time')
        if time_str:
            try:
                result.event_time = time.fromisoformat(time_str)
            except (ValueError, TypeError):
                # Try parsing with seconds
                try:
                    result.event_time = time.fromisoformat(f"{time_str}:00")
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse event_time: {time_str}")

        # Parse prices
        price_low = data.get('price_low')
        if price_low is not None:
            try:
                result.price_low = Decimal(str(price_low))
            except Exception:
                logger.warning(f"Could not parse price_low: {price_low}")

        price_high = data.get('price_high')
        if price_high is not None:
            try:
                result.price_high = Decimal(str(price_high))
            except Exception:
                logger.warning(f"Could not parse price_high: {price_high}")

        # Parse sold out
        result.is_sold_out = bool(data.get('is_sold_out', False))

        return result

    def _truncate_html(self, html_content: str, max_chars: int = 50000) -> str:
        """
        Truncate HTML content to fit within token limits.

        Args:
            html_content: Raw HTML content
            max_chars: Maximum characters to keep

        Returns:
            Truncated HTML content
        """
        if len(html_content) <= max_chars:
            return html_content

        logger.warning(f"Truncating HTML from {len(html_content)} to {max_chars} chars")
        return html_content[:max_chars] + "\n... [truncated]"

    def get_supported_models(self) -> list[str]:
        """
        Get list of supported models for this provider.

        Returns:
            List of model identifiers
        """
        return [self.default_model]
