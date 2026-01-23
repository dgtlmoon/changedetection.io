"""
Anthropic LLM extraction provider.

Supports Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Sonnet, and Claude 3 Haiku.
"""

import os
from decimal import Decimal
from typing import Any

from changedetectionio.llm_extractors.base import (
    LLMExtractor,
    LLMExtractionResult,
    LLMAuthenticationError,
    LLMProviderError,
    LLMRateLimitError,
    DEFAULT_EXTRACTION_PROMPT,
)

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# Cost per 1M tokens as of January 2025 (USD)
ANTHROPIC_MODEL_COSTS = {
    'claude-sonnet-4-20250514': {'input': Decimal('3.00'), 'output': Decimal('15.00')},
    'claude-3-5-sonnet-20241022': {'input': Decimal('3.00'), 'output': Decimal('15.00')},
    'claude-3-5-haiku-20241022': {'input': Decimal('0.80'), 'output': Decimal('4.00')},
    'claude-3-opus-20240229': {'input': Decimal('15.00'), 'output': Decimal('75.00')},
    'claude-3-sonnet-20240229': {'input': Decimal('3.00'), 'output': Decimal('15.00')},
    'claude-3-haiku-20240307': {'input': Decimal('0.25'), 'output': Decimal('1.25')},
}


class AnthropicExtractor(LLMExtractor):
    """
    Anthropic-based LLM extractor.

    Uses the Anthropic API to extract event data from HTML content.
    Requires an API key, which can be set via api_key parameter or
    ANTHROPIC_API_KEY environment variable.
    """

    provider_name = "anthropic"
    default_model = "claude-3-5-haiku-20241022"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout: int = 30,
    ):
        """
        Initialize the Anthropic extractor.

        Args:
            api_key: Anthropic API key (or set ANTHROPIC_API_KEY env var)
            model: Model to use (default: claude-3-5-haiku-20241022)
            api_base_url: Custom API base URL
            timeout: Request timeout in seconds
        """
        super().__init__(api_key, model, api_base_url, timeout)

        # Use environment variable if no key provided
        if not self.api_key:
            self.api_key = os.environ.get('ANTHROPIC_API_KEY')

        # Set cost based on model
        model_costs = ANTHROPIC_MODEL_COSTS.get(self.model, ANTHROPIC_MODEL_COSTS['claude-3-5-haiku-20241022'])
        self.input_cost_per_million = model_costs['input']
        self.output_cost_per_million = model_costs['output']

    def is_configured(self) -> bool:
        """Check if Anthropic is properly configured."""
        return bool(self.api_key)

    def get_supported_models(self) -> list[str]:
        """Get list of supported Anthropic models."""
        return list(ANTHROPIC_MODEL_COSTS.keys())

    async def extract(
        self,
        html_content: str,
        prompt_template: str | None = None,
    ) -> LLMExtractionResult:
        """
        Extract event data from HTML using Anthropic.

        Args:
            html_content: Raw HTML content to analyze
            prompt_template: Custom prompt template (uses default if not provided)

        Returns:
            LLMExtractionResult with extracted data and cost info
        """
        result = LLMExtractionResult(provider=self.provider_name, model=self.model)

        if not self.is_configured():
            result.error = "Anthropic API key not configured"
            logger.error(result.error)
            return result

        # Prepare the prompt
        template = prompt_template or DEFAULT_EXTRACTION_PROMPT
        truncated_html = self._truncate_html(html_content)
        prompt = template.format(html_content=truncated_html)

        try:
            import httpx

            base_url = self.api_base_url or "https://api.anthropic.com/v1"
            url = f"{base_url}/messages"

            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }

            request_body: dict[str, Any] = {
                "model": self.model,
                "max_tokens": 1024,
                "system": "You are a helpful assistant that extracts structured event data from HTML. Always respond with valid JSON only, no other text.",
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=request_body, headers=headers)

                if response.status_code == 401:
                    raise LLMAuthenticationError("Invalid Anthropic API key")
                elif response.status_code == 429:
                    raise LLMRateLimitError("Anthropic rate limit exceeded")
                elif response.status_code != 200:
                    raise LLMProviderError(f"Anthropic API error: {response.status_code} - {response.text}")

                data = response.json()

            # Extract token usage
            usage = data.get('usage', {})
            result.input_tokens = usage.get('input_tokens', 0)
            result.output_tokens = usage.get('output_tokens', 0)
            result.cost_usd = self.calculate_cost(result.input_tokens, result.output_tokens)

            # Parse the response
            content = data['content'][0]['text']
            result.raw_response = content

            parsed_data = self._parse_json_response(content)
            extracted = self._convert_result(parsed_data)

            # Copy extracted values to result
            result.event_name = extracted.event_name
            result.artist = extracted.artist
            result.venue = extracted.venue
            result.event_date = extracted.event_date
            result.event_time = extracted.event_time
            result.price_low = extracted.price_low
            result.price_high = extracted.price_high
            result.is_sold_out = extracted.is_sold_out
            result.success = True

            logger.info(
                f"Anthropic extraction complete: {result.input_tokens} input + "
                f"{result.output_tokens} output tokens = ${result.cost_usd}"
            )

        except (LLMAuthenticationError, LLMRateLimitError, LLMProviderError):
            raise
        except Exception as e:
            result.error = str(e)
            logger.error(f"Anthropic extraction failed: {e}")

        return result
