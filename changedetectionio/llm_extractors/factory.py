"""
Factory for creating LLM extractor instances.

Provides a unified interface for instantiating LLM extractors
based on provider configuration.
"""

from typing import TYPE_CHECKING

from changedetectionio.llm_extractors.base import LLMExtractor, LLMProviderError

if TYPE_CHECKING:
    pass

try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)


# Available providers and their implementations
PROVIDERS = {
    'openai': 'changedetectionio.llm_extractors.openai_provider.OpenAIExtractor',
    'anthropic': 'changedetectionio.llm_extractors.anthropic_provider.AnthropicExtractor',
    'ollama': 'changedetectionio.llm_extractors.ollama_provider.OllamaExtractor',
}


def get_available_providers() -> list[dict]:
    """
    Get list of available LLM providers with their details.

    Returns:
        List of provider info dictionaries
    """
    return [
        {
            'id': 'openai',
            'name': 'OpenAI',
            'description': 'GPT-4, GPT-3.5 Turbo and other OpenAI models',
            'requires_api_key': True,
            'default_model': 'gpt-4o-mini',
        },
        {
            'id': 'anthropic',
            'name': 'Anthropic',
            'description': 'Claude 3.5 Sonnet, Claude 3 Opus, Haiku and other Claude models',
            'requires_api_key': True,
            'default_model': 'claude-3-5-haiku-20241022',
        },
        {
            'id': 'ollama',
            'name': 'Ollama (Local)',
            'description': 'Run LLMs locally with Ollama - no API key needed',
            'requires_api_key': False,
            'default_model': 'llama3.2',
        },
    ]


def create_llm_extractor(
    provider: str,
    api_key: str | None = None,
    model: str | None = None,
    api_base_url: str | None = None,
    timeout: int = 30,
) -> LLMExtractor:
    """
    Create an LLM extractor instance for the specified provider.

    Args:
        provider: Provider name ('openai', 'anthropic', 'ollama')
        api_key: API key for the provider (not needed for Ollama)
        model: Model to use (defaults to provider's default)
        api_base_url: Custom API base URL
        timeout: Request timeout in seconds

    Returns:
        Configured LLMExtractor instance

    Raises:
        LLMProviderError: If provider is not supported
    """
    provider_lower = provider.lower()

    if provider_lower not in PROVIDERS:
        available = ', '.join(PROVIDERS.keys())
        raise LLMProviderError(f"Unknown LLM provider: {provider}. Available: {available}")

    # Import and instantiate the provider class
    module_path = PROVIDERS[provider_lower]
    module_name, class_name = module_path.rsplit('.', 1)

    try:
        import importlib
        module = importlib.import_module(module_name)
        extractor_class = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        raise LLMProviderError(f"Failed to load LLM provider '{provider}': {e}")

    logger.debug(f"Creating LLM extractor: provider={provider}, model={model}")

    return extractor_class(
        api_key=api_key,
        model=model,
        api_base_url=api_base_url,
        timeout=timeout,
    )


def get_provider_models(provider: str) -> list[str]:
    """
    Get list of supported models for a provider.

    Args:
        provider: Provider name

    Returns:
        List of model identifiers
    """
    try:
        extractor = create_llm_extractor(provider)
        return extractor.get_supported_models()
    except Exception:
        return []
