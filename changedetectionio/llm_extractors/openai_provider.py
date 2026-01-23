"""
OpenAI LLM extraction provider.

Supports GPT-4, GPT-4 Turbo, GPT-3.5 Turbo, and other OpenAI chat models.
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
OPENAI_MODEL_COSTS = {
    'gpt-4o': {'input': Decimal('2.50'), 'output': Decimal('10.00')},
    'gpt-4o-mini': {'input': Decimal('0.15'), 'output': Decimal('0.60')},
    'gpt-4-turbo': {'input': Decimal('10.00'), 'output': Decimal('30.00')},
    'gpt-4': {'input': Decimal('30.00'), 'output': Decimal('60.00')},
    'gpt-3.5-turbo': {'input': Decimal('0.50'), 'output': Decimal('1.50')},
    'o1': {'input': Decimal('15.00'), 'output': Decimal('60.00')},
    'o1-mini': {'input': Decimal('3.00'), 'output': Decimal('12.00')},
}


class OpenAIExtractor(LLMExtractor):
    """
    OpenAI-based LLM extractor.

    Uses the OpenAI API to extract event data from HTML content.
    Requires an API key, which can be set via api_key parameter or
    OPENAI_API_KEY environment variable.
    """

    provider_name = "openai"
    default_model = "gpt-4o-mini"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        api_base_url: str | None = None,
        timeout: int = 30,
    ):
        """
        Initialize the OpenAI extractor.

        Args:
            api_key: OpenAI API key (or set OPENAI_API_KEY env var)
            model: Model to use (default: gpt-4o-mini)
            api_base_url: Custom API base URL (for Azure OpenAI or proxies)
            timeout: Request timeout in seconds
        """
        super().__init__(api_key, model, api_base_url, timeout)

        # Use environment variable if no key provided
        if not self.api_key:
            self.api_key = os.environ.get('OPENAI_API_KEY')

        # Set cost based on model
        model_costs = OPENAI_MODEL_COSTS.get(self.model, OPENAI_MODEL_COSTS['gpt-4o-mini'])
        self.input_cost_per_million = model_costs['input']
        self.output_cost_per_million = model_costs['output']

    def is_configured(self) -> bool:
        """Check if OpenAI is properly configured."""
        return bool(self.api_key)

    def get_supported_models(self) -> list[str]:
        """Get list of supported OpenAI models."""
        return list(OPENAI_MODEL_COSTS.keys())

    async def extract(
        self,
        html_content: str,
        prompt_template: str | None = None,
    ) -> LLMExtractionResult:
        """
        Extract event data from HTML using OpenAI.

        Args:
            html_content: Raw HTML content to analyze
            prompt_template: Custom prompt template (uses default if not provided)

        Returns:
            LLMExtractionResult with extracted data and cost info
        """
        result = LLMExtractionResult(provider=self.provider_name, model=self.model)

        if not self.is_configured():
            result.error = "OpenAI API key not configured"
            logger.error(result.error)
            return result

        # Prepare the prompt
        template = prompt_template or DEFAULT_EXTRACTION_PROMPT
        truncated_html = self._truncate_html(html_content)
        prompt = template.format(html_content=truncated_html)

        try:
            # Import httpx for async HTTP requests
            import httpx

            base_url = self.api_base_url or "https://api.openai.com/v1"
            url = f"{base_url}/chat/completions"

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }

            # Build request body
            request_body: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful assistant that extracts structured event data from HTML. Always respond with valid JSON only."
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,  # Low temperature for consistent extraction
            }

            # Add response format for models that support it
            if self.model in ['gpt-4o', 'gpt-4o-mini', 'gpt-4-turbo']:
                request_body["response_format"] = {"type": "json_object"}

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=request_body, headers=headers)

                if response.status_code == 401:
                    raise LLMAuthenticationError("Invalid OpenAI API key")
                elif response.status_code == 429:
                    raise LLMRateLimitError("OpenAI rate limit exceeded")
                elif response.status_code != 200:
                    raise LLMProviderError(f"OpenAI API error: {response.status_code} - {response.text}")

                data = response.json()

            # Extract token usage
            usage = data.get('usage', {})
            result.input_tokens = usage.get('prompt_tokens', 0)
            result.output_tokens = usage.get('completion_tokens', 0)
            result.cost_usd = self.calculate_cost(result.input_tokens, result.output_tokens)

            # Parse the response
            content = data['choices'][0]['message']['content']
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
                f"OpenAI extraction complete: {result.input_tokens} input + "
                f"{result.output_tokens} output tokens = ${result.cost_usd}"
            )

        except (LLMAuthenticationError, LLMRateLimitError, LLMProviderError):
            raise
        except Exception as e:
            result.error = str(e)
            logger.error(f"OpenAI extraction failed: {e}")

        return result
