"""
LLM Extraction Module for Change Detection

This module provides AI-powered extraction of structured event data using various LLM providers.
It supports OpenAI, Anthropic, and Ollama as backends with a unified interface.

The LLM extraction is disabled by default and falls back to CSS selectors if it fails.
"""

from changedetectionio.llm_extractors.base import (
    LLMExtractor,
    LLMExtractionResult,
    LLMExtractionError,
    LLMProviderError,
    LLMRateLimitError,
    LLMAuthenticationError,
    LLMCostRecord,
    DEFAULT_EXTRACTION_PROMPT,
)
from changedetectionio.llm_extractors.factory import (
    create_llm_extractor,
    get_available_providers,
    get_provider_models,
)
from changedetectionio.llm_extractors.service import (
    LLMExtractionService,
    ExtractionConfig,
    get_llm_extraction_service,
)

__all__ = [
    # Base classes and exceptions
    'LLMExtractor',
    'LLMExtractionResult',
    'LLMExtractionError',
    'LLMProviderError',
    'LLMRateLimitError',
    'LLMAuthenticationError',
    'LLMCostRecord',
    'DEFAULT_EXTRACTION_PROMPT',
    # Factory functions
    'create_llm_extractor',
    'get_available_providers',
    'get_provider_models',
    # Service
    'LLMExtractionService',
    'ExtractionConfig',
    'get_llm_extraction_service',
]
