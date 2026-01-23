"""
LLM Extraction Service

This service provides the main interface for LLM-based extraction with:
- Automatic provider selection based on settings
- Fallback to CSS selectors when LLM fails
- Cost tracking and logging
- Rate limiting awareness
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from changedetectionio.llm_extractors.base import (
    LLMExtractor,
    LLMExtractionResult,
    LLMExtractionError,
    LLMCostRecord,
)
from changedetectionio.llm_extractors.factory import create_llm_extractor

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


@dataclass
class ExtractionConfig:
    """Configuration for LLM extraction from app settings."""

    enabled: bool = False
    provider: str | None = None
    api_key: str | None = None
    model: str | None = None
    api_base_url: str | None = None
    prompt_template: str | None = None
    timeout: int = 30
    fallback_to_css: bool = True
    max_html_chars: int = 50000

    @classmethod
    def from_settings(cls, settings: dict) -> 'ExtractionConfig':
        """Create config from app settings dictionary."""
        llm_settings = settings.get('application', {}).get('llm_extraction', {})
        return cls(
            enabled=llm_settings.get('enabled', False),
            provider=llm_settings.get('provider'),
            api_key=llm_settings.get('api_key'),
            model=llm_settings.get('model'),
            api_base_url=llm_settings.get('api_base_url'),
            prompt_template=llm_settings.get('prompt_template'),
            timeout=llm_settings.get('timeout', 30),
            fallback_to_css=llm_settings.get('fallback_to_css', True),
            max_html_chars=llm_settings.get('max_html_chars', 50000),
        )


class LLMExtractionService:
    """
    Service for performing LLM-based extraction with fallback support.

    Usage:
        from changedetectionio.llm_extractors.service import LLMExtractionService

        service = LLMExtractionService(datastore)

        # Extract using LLM with fallback to CSS
        result = await service.extract_with_fallback(
            html_content=html,
            css_selectors=selectors,
            watch_uuid=uuid,
        )
    """

    def __init__(self, datastore=None):
        """
        Initialize the extraction service.

        Args:
            datastore: Optional datastore for accessing settings and storing costs
        """
        self.datastore = datastore
        self._extractor: LLMExtractor | None = None
        self._config: ExtractionConfig | None = None

    def _get_config(self) -> ExtractionConfig:
        """Get current extraction configuration from datastore."""
        if self.datastore:
            settings = self.datastore.data.get('settings', {})
            return ExtractionConfig.from_settings(settings)
        return ExtractionConfig()

    def _get_extractor(self, config: ExtractionConfig) -> LLMExtractor | None:
        """
        Get or create an LLM extractor based on config.

        Args:
            config: Extraction configuration

        Returns:
            Configured LLMExtractor or None if not configured
        """
        if not config.enabled or not config.provider:
            return None

        try:
            return create_llm_extractor(
                provider=config.provider,
                api_key=config.api_key,
                model=config.model,
                api_base_url=config.api_base_url,
                timeout=config.timeout,
            )
        except Exception as e:
            logger.error(f"Failed to create LLM extractor: {e}")
            return None

    def is_enabled(self) -> bool:
        """Check if LLM extraction is enabled and configured."""
        config = self._get_config()
        if not config.enabled:
            return False

        extractor = self._get_extractor(config)
        return extractor is not None and extractor.is_configured()

    async def extract(
        self,
        html_content: str,
        watch_uuid: str | None = None,
    ) -> LLMExtractionResult:
        """
        Extract event data from HTML using the configured LLM.

        Args:
            html_content: Raw HTML content to analyze
            watch_uuid: Optional watch UUID for cost tracking

        Returns:
            LLMExtractionResult with extracted data and cost info
        """
        config = self._get_config()
        extractor = self._get_extractor(config)

        if not extractor:
            result = LLMExtractionResult()
            result.error = "LLM extraction not enabled or not configured"
            return result

        if not extractor.is_configured():
            result = LLMExtractionResult()
            result.error = f"LLM provider '{config.provider}' not properly configured"
            return result

        # Truncate HTML if needed
        if len(html_content) > config.max_html_chars:
            logger.warning(
                f"Truncating HTML from {len(html_content)} to {config.max_html_chars} chars"
            )
            html_content = html_content[:config.max_html_chars]

        # Perform extraction
        result = await extractor.extract(
            html_content=html_content,
            prompt_template=config.prompt_template,
        )

        # Track costs
        if self.datastore and result.cost_usd > 0:
            self._record_cost(result, watch_uuid)

        return result

    async def extract_with_fallback(
        self,
        html_content: str,
        css_selectors: dict[str, str] | None = None,
        watch_uuid: str | None = None,
    ) -> tuple[Any, str]:
        """
        Extract event data using LLM with fallback to CSS selectors.

        Args:
            html_content: Raw HTML content to analyze
            css_selectors: CSS selectors for fallback extraction
            watch_uuid: Optional watch UUID for cost tracking

        Returns:
            Tuple of (ExtractionResult, extraction_method)
            extraction_method is 'llm', 'css', or 'none'
        """
        config = self._get_config()

        # Try LLM extraction first if enabled
        if config.enabled:
            try:
                llm_result = await self.extract(html_content, watch_uuid)

                if llm_result.success:
                    logger.info(f"LLM extraction successful for watch {watch_uuid}")
                    return llm_result.to_extraction_result(), 'llm'

                logger.warning(f"LLM extraction failed: {llm_result.error}")

            except LLMExtractionError as e:
                logger.error(f"LLM extraction error: {e}")

            except Exception as e:
                logger.error(f"Unexpected LLM extraction error: {e}")

        # Fall back to CSS selectors if enabled and available
        if config.fallback_to_css and css_selectors:
            try:
                from tasks.event_extractor import EventDataExtractor

                extractor = EventDataExtractor()
                result = extractor.extract(html_content, css_selectors)

                if any(v is not None for v in result.to_dict().values()):
                    logger.info(f"CSS extraction successful for watch {watch_uuid}")
                    return result, 'css'

            except Exception as e:
                logger.error(f"CSS extraction error: {e}")

        # No extraction succeeded
        from tasks.event_extractor import ExtractionResult
        return ExtractionResult(), 'none'

    def _record_cost(self, result: LLMExtractionResult, watch_uuid: str | None = None):
        """
        Record LLM API call cost to datastore.

        Args:
            result: LLM extraction result with cost info
            watch_uuid: Optional watch UUID
        """
        if not self.datastore:
            return

        try:
            cost_tracking = self.datastore.data['settings']['application'].get('llm_cost_tracking', {})

            # Update totals
            current_total = Decimal(cost_tracking.get('total_cost_usd', '0'))
            cost_tracking['total_cost_usd'] = str(current_total + result.cost_usd)
            cost_tracking['total_input_tokens'] = cost_tracking.get('total_input_tokens', 0) + result.input_tokens
            cost_tracking['total_output_tokens'] = cost_tracking.get('total_output_tokens', 0) + result.output_tokens
            cost_tracking['call_count'] = cost_tracking.get('call_count', 0) + 1

            self.datastore.data['settings']['application']['llm_cost_tracking'] = cost_tracking

            logger.debug(
                f"Recorded LLM cost: ${result.cost_usd} "
                f"(total: ${cost_tracking['total_cost_usd']}, "
                f"calls: {cost_tracking['call_count']})"
            )

        except Exception as e:
            logger.error(f"Failed to record LLM cost: {e}")

    def get_cost_summary(self) -> dict[str, Any]:
        """
        Get summary of LLM API costs.

        Returns:
            Dictionary with cost tracking information
        """
        if not self.datastore:
            return {}

        cost_tracking = self.datastore.data['settings']['application'].get('llm_cost_tracking', {})
        return {
            'total_cost_usd': cost_tracking.get('total_cost_usd', '0'),
            'total_input_tokens': cost_tracking.get('total_input_tokens', 0),
            'total_output_tokens': cost_tracking.get('total_output_tokens', 0),
            'call_count': cost_tracking.get('call_count', 0),
            'last_reset': cost_tracking.get('last_reset'),
        }

    def reset_cost_tracking(self):
        """Reset cost tracking counters."""
        if not self.datastore:
            return

        self.datastore.data['settings']['application']['llm_cost_tracking'] = {
            'enabled': True,
            'total_cost_usd': '0',
            'total_input_tokens': 0,
            'total_output_tokens': 0,
            'call_count': 0,
            'last_reset': datetime.utcnow().isoformat(),
        }
        logger.info("LLM cost tracking reset")


# Singleton service instance (initialized with datastore when needed)
_service_instance: LLMExtractionService | None = None


def get_llm_extraction_service(datastore=None) -> LLMExtractionService:
    """
    Get or create the LLM extraction service singleton.

    Args:
        datastore: Optional datastore to use (updates existing service)

    Returns:
        LLMExtractionService instance
    """
    global _service_instance

    if _service_instance is None:
        _service_instance = LLMExtractionService(datastore)
    elif datastore is not None:
        _service_instance.datastore = datastore

    return _service_instance
