"""
Ollama LLM extraction provider.

Supports local LLM models running via Ollama.
No API key required - connects to local Ollama server.
"""

import os
from decimal import Decimal
from typing import Any

from changedetectionio.llm_extractors.base import (
    LLMExtractor,
    LLMExtractionResult,
    LLMProviderError,
    DEFAULT_EXTRACTION_PROMPT,
)

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# Common Ollama models for structured extraction
OLLAMA_RECOMMENDED_MODELS = [
    'llama3.2',
    'llama3.1',
    'mistral',
    'mixtral',
    'gemma2',
    'phi3',
    'qwen2.5',
    'deepseek-coder-v2',
]


class OllamaExtractor(LLMExtractor):
    """
    Ollama-based LLM extractor for local models.

    Uses the Ollama API to extract event data from HTML content.
    Connects to a local Ollama server (default: http://localhost:11434).
    No API key required.
    """

    provider_name = "ollama"
    default_model = "llama3.2"

    # Ollama is free (local), so no cost
    input_cost_per_million = Decimal('0')
    output_cost_per_million = Decimal('0')

    def __init__(
        self,
        api_key: str | None = None,  # Not used for Ollama
        model: str | None = None,
        api_base_url: str | None = None,
        timeout: int = 120,  # Longer timeout for local models
    ):
        """
        Initialize the Ollama extractor.

        Args:
            api_key: Not used for Ollama (kept for interface compatibility)
            model: Model to use (default: llama3.2)
            api_base_url: Ollama server URL (default: http://localhost:11434)
            timeout: Request timeout in seconds (default: 120 for local models)
        """
        super().__init__(api_key, model, api_base_url, timeout)

        # Get Ollama URL from environment or use default
        if not self.api_base_url:
            self.api_base_url = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')

    def is_configured(self) -> bool:
        """
        Check if Ollama is properly configured.

        For Ollama, we just check that the URL is set. The model
        availability is checked at extraction time.
        """
        return bool(self.api_base_url)

    def get_supported_models(self) -> list[str]:
        """Get list of recommended Ollama models."""
        return OLLAMA_RECOMMENDED_MODELS

    async def _check_model_available(self) -> bool:
        """
        Check if the configured model is available on the Ollama server.

        Returns:
            True if model is available
        """
        try:
            import httpx

            url = f"{self.api_base_url}/api/tags"
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    data = response.json()
                    models = [m['name'] for m in data.get('models', [])]
                    # Check if model name matches (with or without :latest suffix)
                    return any(
                        self.model == m or
                        self.model == m.split(':')[0] or
                        f"{self.model}:latest" == m
                        for m in models
                    )
        except Exception:
            pass
        return False

    async def extract(
        self,
        html_content: str,
        prompt_template: str | None = None,
    ) -> LLMExtractionResult:
        """
        Extract event data from HTML using Ollama.

        Args:
            html_content: Raw HTML content to analyze
            prompt_template: Custom prompt template (uses default if not provided)

        Returns:
            LLMExtractionResult with extracted data and cost info
        """
        result = LLMExtractionResult(provider=self.provider_name, model=self.model)

        if not self.is_configured():
            result.error = "Ollama URL not configured"
            logger.error(result.error)
            return result

        # Prepare the prompt
        template = prompt_template or DEFAULT_EXTRACTION_PROMPT
        truncated_html = self._truncate_html(html_content)
        prompt = template.format(html_content=truncated_html)

        try:
            import httpx

            url = f"{self.api_base_url}/api/generate"

            request_body: dict[str, Any] = {
                "model": self.model,
                "prompt": f"You are a helpful assistant that extracts structured event data from HTML. Always respond with valid JSON only, no other text.\n\n{prompt}",
                "stream": False,
                "format": "json",  # Request JSON output
                "options": {
                    "temperature": 0.1,  # Low temperature for consistent extraction
                }
            }

            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=request_body)

                if response.status_code == 404:
                    raise LLMProviderError(f"Ollama model '{self.model}' not found. Run 'ollama pull {self.model}' to download it.")
                elif response.status_code != 200:
                    raise LLMProviderError(f"Ollama API error: {response.status_code} - {response.text}")

                data = response.json()

            # Extract token counts (Ollama provides these)
            result.input_tokens = data.get('prompt_eval_count', 0)
            result.output_tokens = data.get('eval_count', 0)
            result.cost_usd = Decimal('0')  # Ollama is free

            # Parse the response
            content = data.get('response', '')
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
                f"Ollama extraction complete: {result.input_tokens} input + "
                f"{result.output_tokens} output tokens (free)"
            )

        except LLMProviderError:
            raise
        except Exception as e:
            result.error = str(e)
            logger.error(f"Ollama extraction failed: {e}")

        return result
