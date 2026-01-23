"""
Tests for LLM Extraction Module

Tests the LLM provider abstraction, factory, and extraction service.
"""

import pytest
from decimal import Decimal
from datetime import date, time
from unittest.mock import AsyncMock, MagicMock, patch

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
    PROVIDERS,
)
from changedetectionio.llm_extractors.openai_provider import OpenAIExtractor, OPENAI_MODEL_COSTS
from changedetectionio.llm_extractors.anthropic_provider import AnthropicExtractor, ANTHROPIC_MODEL_COSTS
from changedetectionio.llm_extractors.ollama_provider import OllamaExtractor, OLLAMA_RECOMMENDED_MODELS
from changedetectionio.llm_extractors.service import (
    LLMExtractionService,
    ExtractionConfig,
    get_llm_extraction_service,
)


# =============================================================================
# Test Data Classes
# =============================================================================


class TestLLMExtractionResult:
    """Tests for LLMExtractionResult dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        result = LLMExtractionResult()

        assert result.event_name is None
        assert result.artist is None
        assert result.venue is None
        assert result.event_date is None
        assert result.event_time is None
        assert result.price_low is None
        assert result.price_high is None
        assert result.is_sold_out is False
        assert result.success is False
        assert result.error is None
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.cost_usd == Decimal('0')

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = LLMExtractionResult(
            event_name="Test Event",
            artist="Test Artist",
            venue="Test Venue",
            event_date=date(2025, 6, 15),
            event_time=time(19, 30),
            price_low=Decimal('25.00'),
            price_high=Decimal('75.00'),
            is_sold_out=True,
        )

        d = result.to_dict()

        assert d['event_name'] == "Test Event"
        assert d['artist'] == "Test Artist"
        assert d['venue'] == "Test Venue"
        assert d['event_date'] == "2025-06-15"
        assert d['event_time'] == "19:30:00"
        assert d['price_low'] == 25.0
        assert d['price_high'] == 75.0
        assert d['is_sold_out'] is True

    def test_to_dict_with_none_values(self):
        """Test conversion to dictionary with None values."""
        result = LLMExtractionResult()
        d = result.to_dict()

        assert d['event_name'] is None
        assert d['event_date'] is None
        assert d['price_low'] is None

    def test_to_extraction_result(self):
        """Test conversion to ExtractionResult for compatibility."""
        result = LLMExtractionResult(
            event_name="Concert",
            artist="Band",
            price_low=Decimal('50'),
            success=True,
        )

        extraction_result = result.to_extraction_result()

        assert extraction_result.event_name == "Concert"
        assert extraction_result.artist == "Band"
        assert extraction_result.current_price_low == Decimal('50')


class TestLLMCostRecord:
    """Tests for LLMCostRecord dataclass."""

    def test_default_values(self):
        """Test default values are set correctly."""
        record = LLMCostRecord()

        assert record.provider == ""
        assert record.model == ""
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.cost_usd == Decimal('0')
        assert record.watch_uuid is None
        assert record.success is False
        assert record.timestamp is not None


# =============================================================================
# Test Exceptions
# =============================================================================


class TestExceptions:
    """Tests for LLM extraction exceptions."""

    def test_exception_hierarchy(self):
        """Test exception inheritance."""
        assert issubclass(LLMProviderError, LLMExtractionError)
        assert issubclass(LLMRateLimitError, LLMExtractionError)
        assert issubclass(LLMAuthenticationError, LLMExtractionError)

    def test_exception_messages(self):
        """Test exception messages."""
        error = LLMProviderError("API error")
        assert str(error) == "API error"

        error = LLMRateLimitError("Rate limit exceeded")
        assert str(error) == "Rate limit exceeded"


# =============================================================================
# Test Factory
# =============================================================================


class TestFactory:
    """Tests for the LLM extractor factory."""

    def test_get_available_providers(self):
        """Test getting list of available providers."""
        providers = get_available_providers()

        assert len(providers) == 3
        provider_ids = [p['id'] for p in providers]
        assert 'openai' in provider_ids
        assert 'anthropic' in provider_ids
        assert 'ollama' in provider_ids

    def test_get_available_providers_structure(self):
        """Test provider info structure."""
        providers = get_available_providers()

        for provider in providers:
            assert 'id' in provider
            assert 'name' in provider
            assert 'description' in provider
            assert 'requires_api_key' in provider
            assert 'default_model' in provider

    def test_create_openai_extractor(self):
        """Test creating OpenAI extractor."""
        extractor = create_llm_extractor('openai', api_key='test-key')

        assert isinstance(extractor, OpenAIExtractor)
        assert extractor.provider_name == 'openai'
        assert extractor.api_key == 'test-key'

    def test_create_anthropic_extractor(self):
        """Test creating Anthropic extractor."""
        extractor = create_llm_extractor('anthropic', api_key='test-key')

        assert isinstance(extractor, AnthropicExtractor)
        assert extractor.provider_name == 'anthropic'
        assert extractor.api_key == 'test-key'

    def test_create_ollama_extractor(self):
        """Test creating Ollama extractor."""
        extractor = create_llm_extractor('ollama')

        assert isinstance(extractor, OllamaExtractor)
        assert extractor.provider_name == 'ollama'
        assert extractor.api_key is None  # Ollama doesn't need API key

    def test_create_extractor_with_custom_model(self):
        """Test creating extractor with custom model."""
        extractor = create_llm_extractor('openai', api_key='key', model='gpt-4')

        assert extractor.model == 'gpt-4'

    def test_create_extractor_case_insensitive(self):
        """Test provider name is case-insensitive."""
        extractor1 = create_llm_extractor('OpenAI', api_key='key')
        extractor2 = create_llm_extractor('OPENAI', api_key='key')
        extractor3 = create_llm_extractor('openai', api_key='key')

        assert all(isinstance(e, OpenAIExtractor) for e in [extractor1, extractor2, extractor3])

    def test_create_unknown_provider_raises(self):
        """Test unknown provider raises error."""
        with pytest.raises(LLMProviderError) as exc_info:
            create_llm_extractor('unknown_provider')

        assert 'Unknown LLM provider' in str(exc_info.value)
        assert 'openai' in str(exc_info.value)  # Lists available providers

    def test_get_provider_models(self):
        """Test getting models for a provider."""
        models = get_provider_models('openai')
        assert 'gpt-4o-mini' in models
        assert 'gpt-4' in models


# =============================================================================
# Test OpenAI Provider
# =============================================================================


class TestOpenAIExtractor:
    """Tests for OpenAI extractor."""

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        extractor = OpenAIExtractor(api_key='sk-test123')

        assert extractor.api_key == 'sk-test123'
        assert extractor.is_configured() is True

    def test_init_without_api_key(self):
        """Test initialization without API key."""
        extractor = OpenAIExtractor()

        # May pick up from environment
        if not extractor.api_key:
            assert extractor.is_configured() is False

    def test_default_model(self):
        """Test default model is set."""
        extractor = OpenAIExtractor(api_key='key')

        assert extractor.model == 'gpt-4o-mini'

    def test_custom_model(self):
        """Test custom model."""
        extractor = OpenAIExtractor(api_key='key', model='gpt-4')

        assert extractor.model == 'gpt-4'

    def test_supported_models(self):
        """Test supported models list."""
        extractor = OpenAIExtractor(api_key='key')
        models = extractor.get_supported_models()

        assert 'gpt-4o' in models
        assert 'gpt-4o-mini' in models
        assert 'gpt-4' in models
        assert 'gpt-3.5-turbo' in models

    def test_cost_calculation(self):
        """Test cost calculation."""
        extractor = OpenAIExtractor(api_key='key', model='gpt-4o-mini')

        # GPT-4o-mini: $0.15 / 1M input, $0.60 / 1M output
        cost = extractor.calculate_cost(input_tokens=1000, output_tokens=500)

        # 1000 * 0.15 / 1M + 500 * 0.60 / 1M = 0.00015 + 0.0003 = 0.00045
        expected = Decimal('0.00015') + Decimal('0.0003')
        assert cost == expected

    def test_cost_tracking_different_models(self):
        """Test different models have different costs."""
        cheap = OpenAIExtractor(api_key='key', model='gpt-4o-mini')
        expensive = OpenAIExtractor(api_key='key', model='gpt-4')

        cheap_cost = cheap.calculate_cost(1000, 1000)
        expensive_cost = expensive.calculate_cost(1000, 1000)

        assert expensive_cost > cheap_cost


# =============================================================================
# Test Anthropic Provider
# =============================================================================


class TestAnthropicExtractor:
    """Tests for Anthropic extractor."""

    def test_init_with_api_key(self):
        """Test initialization with API key."""
        extractor = AnthropicExtractor(api_key='sk-ant-test')

        assert extractor.api_key == 'sk-ant-test'
        assert extractor.is_configured() is True

    def test_default_model(self):
        """Test default model is set."""
        extractor = AnthropicExtractor(api_key='key')

        assert extractor.model == 'claude-3-5-haiku-20241022'

    def test_supported_models(self):
        """Test supported models list."""
        extractor = AnthropicExtractor(api_key='key')
        models = extractor.get_supported_models()

        assert 'claude-3-5-sonnet-20241022' in models
        assert 'claude-3-opus-20240229' in models
        assert 'claude-3-haiku-20240307' in models


# =============================================================================
# Test Ollama Provider
# =============================================================================


class TestOllamaExtractor:
    """Tests for Ollama extractor."""

    def test_init_no_api_key_needed(self):
        """Test Ollama doesn't need API key."""
        extractor = OllamaExtractor()

        assert extractor.is_configured() is True
        assert extractor.api_key is None

    def test_default_url(self):
        """Test default Ollama URL."""
        extractor = OllamaExtractor()

        assert extractor.api_base_url == 'http://localhost:11434'

    def test_custom_url(self):
        """Test custom Ollama URL."""
        extractor = OllamaExtractor(api_base_url='http://remote:11434')

        assert extractor.api_base_url == 'http://remote:11434'

    def test_cost_is_zero(self):
        """Test Ollama has zero cost."""
        extractor = OllamaExtractor()
        cost = extractor.calculate_cost(input_tokens=10000, output_tokens=5000)

        assert cost == Decimal('0')

    def test_recommended_models(self):
        """Test recommended models list."""
        extractor = OllamaExtractor()
        models = extractor.get_supported_models()

        assert 'llama3.2' in models
        assert 'mistral' in models


# =============================================================================
# Test Base Extractor Methods
# =============================================================================


class TestBaseExtractorMethods:
    """Tests for base extractor utility methods."""

    def test_parse_json_response_direct(self):
        """Test parsing direct JSON."""
        extractor = OpenAIExtractor(api_key='key')
        data = extractor._parse_json_response('{"event_name": "Test"}')

        assert data['event_name'] == 'Test'

    def test_parse_json_response_with_markdown(self):
        """Test parsing JSON from markdown code block."""
        extractor = OpenAIExtractor(api_key='key')
        response = '''```json
{"event_name": "Test Event"}
```'''
        data = extractor._parse_json_response(response)

        assert data['event_name'] == 'Test Event'

    def test_parse_json_response_with_text(self):
        """Test parsing JSON embedded in text."""
        extractor = OpenAIExtractor(api_key='key')
        response = 'Here is the data: {"event_name": "Show"} Hope this helps!'
        data = extractor._parse_json_response(response)

        assert data['event_name'] == 'Show'

    def test_parse_json_response_invalid(self):
        """Test parsing invalid JSON raises error."""
        extractor = OpenAIExtractor(api_key='key')

        with pytest.raises(ValueError):
            extractor._parse_json_response('not json at all')

    def test_convert_result(self):
        """Test converting parsed data to result."""
        extractor = OpenAIExtractor(api_key='key')
        data = {
            'event_name': 'Concert',
            'artist': 'Band',
            'venue': 'Arena',
            'event_date': '2025-06-15',
            'event_time': '19:30',
            'price_low': 50,
            'price_high': 150.50,
            'is_sold_out': True,
        }

        result = extractor._convert_result(data)

        assert result.event_name == 'Concert'
        assert result.artist == 'Band'
        assert result.venue == 'Arena'
        assert result.event_date == date(2025, 6, 15)
        assert result.event_time == time(19, 30)
        assert result.price_low == Decimal('50')
        assert result.price_high == Decimal('150.50')
        assert result.is_sold_out is True

    def test_convert_result_with_null_values(self):
        """Test converting data with null values."""
        extractor = OpenAIExtractor(api_key='key')
        data = {
            'event_name': None,
            'artist': 'Artist',
            'price_low': None,
        }

        result = extractor._convert_result(data)

        assert result.event_name is None
        assert result.artist == 'Artist'
        assert result.price_low is None

    def test_truncate_html(self):
        """Test HTML truncation."""
        extractor = OpenAIExtractor(api_key='key')
        long_html = 'x' * 60000

        truncated = extractor._truncate_html(long_html, max_chars=50000)

        assert len(truncated) < 60000
        assert '... [truncated]' in truncated

    def test_truncate_html_no_truncation_needed(self):
        """Test no truncation when HTML is short."""
        extractor = OpenAIExtractor(api_key='key')
        short_html = '<html>Short</html>'

        result = extractor._truncate_html(short_html)

        assert result == short_html


# =============================================================================
# Test Extraction Config
# =============================================================================


class TestExtractionConfig:
    """Tests for ExtractionConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = ExtractionConfig()

        assert config.enabled is False
        assert config.provider is None
        assert config.api_key is None
        assert config.fallback_to_css is True
        assert config.timeout == 30

    def test_from_settings(self):
        """Test creating config from settings dict."""
        settings = {
            'application': {
                'llm_extraction': {
                    'enabled': True,
                    'provider': 'openai',
                    'api_key': 'test-key',
                    'model': 'gpt-4',
                    'fallback_to_css': False,
                }
            }
        }

        config = ExtractionConfig.from_settings(settings)

        assert config.enabled is True
        assert config.provider == 'openai'
        assert config.api_key == 'test-key'
        assert config.model == 'gpt-4'
        assert config.fallback_to_css is False

    def test_from_empty_settings(self):
        """Test creating config from empty settings."""
        config = ExtractionConfig.from_settings({})

        assert config.enabled is False
        assert config.provider is None


# =============================================================================
# Test LLM Extraction Service
# =============================================================================


class TestLLMExtractionService:
    """Tests for LLM extraction service."""

    def test_init_without_datastore(self):
        """Test initialization without datastore."""
        service = LLMExtractionService()

        assert service.datastore is None

    def test_is_enabled_without_datastore(self):
        """Test is_enabled returns False without datastore."""
        service = LLMExtractionService()

        assert service.is_enabled() is False

    def test_is_enabled_with_disabled_settings(self):
        """Test is_enabled returns False when disabled in settings."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_extraction': {
                        'enabled': False,
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)

        assert service.is_enabled() is False

    def test_is_enabled_with_enabled_settings(self):
        """Test is_enabled returns True when properly configured."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_extraction': {
                        'enabled': True,
                        'provider': 'openai',
                        'api_key': 'test-key',
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)

        assert service.is_enabled() is True

    def test_get_cost_summary(self):
        """Test getting cost summary."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_cost_tracking': {
                        'total_cost_usd': '1.50',
                        'total_input_tokens': 10000,
                        'total_output_tokens': 5000,
                        'call_count': 10,
                        'last_reset': '2025-01-01T00:00:00',
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)
        summary = service.get_cost_summary()

        assert summary['total_cost_usd'] == '1.50'
        assert summary['total_input_tokens'] == 10000
        assert summary['call_count'] == 10

    def test_reset_cost_tracking(self):
        """Test resetting cost tracking."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_cost_tracking': {
                        'total_cost_usd': '100',
                        'call_count': 100,
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)
        service.reset_cost_tracking()

        cost_tracking = datastore.data['settings']['application']['llm_cost_tracking']
        assert cost_tracking['total_cost_usd'] == '0'
        assert cost_tracking['call_count'] == 0
        assert cost_tracking['last_reset'] is not None


class TestGetLLMExtractionServiceSingleton:
    """Tests for the service singleton function."""

    def test_returns_service_instance(self):
        """Test function returns service instance."""
        service = get_llm_extraction_service()

        assert isinstance(service, LLMExtractionService)

    def test_updates_datastore(self):
        """Test function updates datastore on existing instance."""
        service1 = get_llm_extraction_service()
        datastore = MagicMock()
        service2 = get_llm_extraction_service(datastore)

        # Should be same instance with updated datastore
        assert service2.datastore == datastore


# =============================================================================
# Test Default Prompt Template
# =============================================================================


class TestDefaultPromptTemplate:
    """Tests for the default extraction prompt template."""

    def test_prompt_has_placeholder(self):
        """Test prompt has html_content placeholder."""
        assert '{html_content}' in DEFAULT_EXTRACTION_PROMPT

    def test_prompt_requests_json(self):
        """Test prompt requests JSON output."""
        assert 'JSON' in DEFAULT_EXTRACTION_PROMPT

    def test_prompt_lists_fields(self):
        """Test prompt lists expected fields."""
        assert 'event_name' in DEFAULT_EXTRACTION_PROMPT
        assert 'artist' in DEFAULT_EXTRACTION_PROMPT
        assert 'venue' in DEFAULT_EXTRACTION_PROMPT
        assert 'event_date' in DEFAULT_EXTRACTION_PROMPT
        assert 'price_low' in DEFAULT_EXTRACTION_PROMPT
        assert 'is_sold_out' in DEFAULT_EXTRACTION_PROMPT


# =============================================================================
# Integration Tests (require mocking HTTP)
# =============================================================================


class TestOpenAIExtractorIntegration:
    """Integration tests for OpenAI extractor with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Test successful extraction."""
        extractor = OpenAIExtractor(api_key='test-key')

        mock_response = {
            'choices': [{
                'message': {
                    'content': '{"event_name": "Concert", "artist": "Band", "is_sold_out": false}'
                }
            }],
            'usage': {
                'prompt_tokens': 100,
                'completion_tokens': 50,
            }
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response

            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value = mock_client

            result = await extractor.extract('<html>Test</html>')

            assert result.success is True
            assert result.event_name == 'Concert'
            assert result.artist == 'Band'
            assert result.input_tokens == 100
            assert result.output_tokens == 50

    @pytest.mark.asyncio
    async def test_extract_auth_error(self):
        """Test extraction with authentication error."""
        extractor = OpenAIExtractor(api_key='invalid-key')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.text = 'Unauthorized'

            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with pytest.raises(LLMAuthenticationError):
                await extractor.extract('<html>Test</html>')

    @pytest.mark.asyncio
    async def test_extract_rate_limit_error(self):
        """Test extraction with rate limit error."""
        extractor = OpenAIExtractor(api_key='test-key')

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.text = 'Rate limit exceeded'

            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with pytest.raises(LLMRateLimitError):
                await extractor.extract('<html>Test</html>')


class TestAnthropicExtractorIntegration:
    """Integration tests for Anthropic extractor with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Test successful extraction."""
        extractor = AnthropicExtractor(api_key='test-key')

        mock_response = {
            'content': [{
                'text': '{"event_name": "Show", "venue": "Theater"}'
            }],
            'usage': {
                'input_tokens': 200,
                'output_tokens': 30,
            }
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response

            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value = mock_client

            result = await extractor.extract('<html>Test</html>')

            assert result.success is True
            assert result.event_name == 'Show'
            assert result.venue == 'Theater'


class TestOllamaExtractorIntegration:
    """Integration tests for Ollama extractor with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_extract_success(self):
        """Test successful extraction."""
        extractor = OllamaExtractor()

        mock_response = {
            'response': '{"event_name": "Local Show", "is_sold_out": true}',
            'prompt_eval_count': 500,
            'eval_count': 100,
        }

        with patch('httpx.AsyncClient') as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)

            mock_response_obj = MagicMock()
            mock_response_obj.status_code = 200
            mock_response_obj.json.return_value = mock_response

            mock_client.post = AsyncMock(return_value=mock_response_obj)
            mock_client_class.return_value = mock_client

            result = await extractor.extract('<html>Test</html>')

            assert result.success is True
            assert result.event_name == 'Local Show'
            assert result.is_sold_out is True
            assert result.cost_usd == Decimal('0')  # Ollama is free


# =============================================================================
# Test Service Integration
# =============================================================================


class TestServiceExtractWithFallback:
    """Tests for extract_with_fallback method."""

    @pytest.mark.asyncio
    async def test_fallback_to_css_when_llm_disabled(self):
        """Test fallback to CSS when LLM is disabled."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_extraction': {
                        'enabled': False,
                        'fallback_to_css': True,
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)

        html = '''<html><h1 class="title">Test Event</h1></html>'''
        css_selectors = {'event_name': 'h1.title'}

        result, method = await service.extract_with_fallback(html, css_selectors)

        assert method == 'css'
        assert result.event_name == 'Test Event'

    @pytest.mark.asyncio
    async def test_returns_none_when_no_extraction_possible(self):
        """Test returns empty result when no extraction possible."""
        datastore = MagicMock()
        datastore.data = {
            'settings': {
                'application': {
                    'llm_extraction': {
                        'enabled': False,
                        'fallback_to_css': False,
                    }
                }
            }
        }

        service = LLMExtractionService(datastore)

        result, method = await service.extract_with_fallback('<html></html>', None)

        assert method == 'none'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
