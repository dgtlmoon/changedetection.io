"""
Tests for LLM Extraction UI (US-026)

Tests the settings page UI components for AI extraction configuration.
"""

import pytest
from unittest.mock import patch, MagicMock


class TestLLMExtractionForm:
    """Tests for LLMExtractionForm in forms.py"""

    def test_form_fields_exist(self):
        """Test that all required form fields are defined."""
        from changedetectionio.forms import LLMExtractionForm

        form = LLMExtractionForm()

        # Check all required fields exist
        assert hasattr(form, 'enabled')
        assert hasattr(form, 'provider')
        assert hasattr(form, 'api_key')
        assert hasattr(form, 'model')
        assert hasattr(form, 'api_base_url')
        assert hasattr(form, 'prompt_template')
        assert hasattr(form, 'timeout')
        assert hasattr(form, 'fallback_to_css')
        assert hasattr(form, 'max_html_chars')

    def test_provider_choices(self):
        """Test that provider dropdown has correct choices."""
        from changedetectionio.forms import LLMExtractionForm

        form = LLMExtractionForm()
        provider_choices = [choice[0] for choice in form.provider.choices]

        assert '' in provider_choices  # Empty default
        assert 'openai' in provider_choices
        assert 'anthropic' in provider_choices
        assert 'ollama' in provider_choices

    def test_default_values(self):
        """Test form default values."""
        from changedetectionio.forms import LLMExtractionForm

        form = LLMExtractionForm()

        assert form.enabled.default == False
        assert form.timeout.default == 30
        assert form.fallback_to_css.default == True
        assert form.max_html_chars.default == 50000

    def test_form_in_global_settings(self):
        """Test that LLMExtractionForm is included in globalSettingsApplicationForm."""
        from changedetectionio.forms import globalSettingsApplicationForm

        form = globalSettingsApplicationForm()

        assert hasattr(form, 'llm_extraction')
        assert hasattr(form.llm_extraction.form, 'enabled')
        assert hasattr(form.llm_extraction.form, 'provider')


class TestLLMSettingsEndpoints:
    """Tests for LLM settings API endpoints."""

    def test_reset_llm_costs_endpoint_exists(self, client):
        """Test that the reset costs endpoint exists."""
        # Should redirect to login if not authenticated
        response = client.get('/settings/reset-llm-costs')
        # 302 = redirect to login, 200 = success
        assert response.status_code in [200, 302]

    def test_test_llm_extraction_endpoint_exists(self, client):
        """Test that the test extraction endpoint exists."""
        response = client.post('/settings/test-llm-extraction',
                              json={'url': 'https://example.com', 'provider': 'openai'},
                              content_type='application/json')
        # Should return 400 (missing API key) or 302 (auth redirect)
        assert response.status_code in [400, 302, 500]

    def test_llm_provider_models_endpoint_exists(self, client):
        """Test that the provider models endpoint exists."""
        response = client.get('/settings/llm-provider-models/openai')
        # Should return JSON with models
        assert response.status_code in [200, 302]

    def test_llm_provider_models_invalid_provider(self, client):
        """Test that invalid provider returns error."""
        response = client.get('/settings/llm-provider-models/invalid_provider')
        # Should return 400 for unknown provider or 302 for auth
        assert response.status_code in [400, 302]


class TestLLMCostTracking:
    """Tests for LLM cost tracking functionality."""

    def test_cost_summary_in_settings_context(self):
        """Test that cost summary is passed to settings template."""
        from changedetectionio.llm_extractors.service import LLMExtractionService

        service = LLMExtractionService()
        summary = service.get_cost_summary()

        # Should return empty dict when no datastore
        assert isinstance(summary, dict)

    def test_cost_summary_structure(self):
        """Test that cost summary has expected structure."""
        from changedetectionio.llm_extractors.service import LLMExtractionService

        # Create mock datastore with cost tracking data
        mock_datastore = MagicMock()
        mock_datastore.data = {
            'settings': {
                'application': {
                    'llm_cost_tracking': {
                        'total_cost_usd': '1.50',
                        'total_input_tokens': 10000,
                        'total_output_tokens': 500,
                        'call_count': 25,
                        'last_reset': '2026-01-01T00:00:00',
                    }
                }
            }
        }

        service = LLMExtractionService(mock_datastore)
        summary = service.get_cost_summary()

        assert 'total_cost_usd' in summary
        assert 'total_input_tokens' in summary
        assert 'total_output_tokens' in summary
        assert 'call_count' in summary


class TestFetchHtmlContentSimple:
    """Tests for the simple HTML content fetcher."""

    def test_function_exists(self):
        """Test that fetch_html_content_simple is importable."""
        from changedetectionio.content_fetchers import fetch_html_content_simple
        assert callable(fetch_html_content_simple)

    def test_fetch_success(self):
        """Test successful HTML fetch."""
        import requests
        with patch.object(requests, 'get') as mock_get:
            mock_response = MagicMock()
            mock_response.text = '<html><body>Test</body></html>'
            mock_response.raise_for_status = MagicMock()
            mock_get.return_value = mock_response

            from changedetectionio.content_fetchers import fetch_html_content_simple
            result = fetch_html_content_simple('https://example.com')
            assert result == '<html><body>Test</body></html>'

    def test_fetch_failure_returns_none(self):
        """Test that failed fetch returns None."""
        import requests
        with patch.object(requests, 'get', side_effect=Exception('Connection failed')):
            from changedetectionio.content_fetchers import fetch_html_content_simple
            result = fetch_html_content_simple('https://example.com')
            assert result is None


class TestLLMSettingsJavaScript:
    """Tests for verifying JavaScript file exists and has correct structure."""

    def test_js_file_exists(self):
        """Test that the LLM settings JavaScript file exists."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'js',
            'llm-settings.js'
        )
        assert os.path.exists(js_path), f"JavaScript file not found at {js_path}"

    def test_js_file_has_provider_models(self):
        """Test that JavaScript file defines provider models."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'js',
            'llm-settings.js'
        )

        with open(js_path, 'r') as f:
            content = f.read()

        assert 'PROVIDER_MODELS' in content
        assert 'openai' in content
        assert 'anthropic' in content
        assert 'ollama' in content
        assert 'gpt-4o-mini' in content
        assert 'claude-3-5-haiku' in content
        assert 'llama3.2' in content

    def test_js_file_has_test_extraction(self):
        """Test that JavaScript file has test extraction handler."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'js',
            'llm-settings.js'
        )

        with open(js_path, 'r') as f:
            content = f.read()

        assert 'handleTestExtraction' in content
        assert 'test-llm-extraction' in content
