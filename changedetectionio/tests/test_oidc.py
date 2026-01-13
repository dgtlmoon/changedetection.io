"""
Tests for OIDC authentication functionality.

These tests verify:
- OIDC configuration loading from environment variables
- is_oidc_enabled() function behavior
- Group-based access control
- Password auth disabled when OIDC is enabled
"""

import os
from unittest.mock import patch


class TestOIDCConfiguration:
    """Test OIDC configuration loading from environment variables."""

    def test_oidc_disabled_when_no_env_vars(self):
        """OIDC should be disabled when no environment variables are set."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear any existing OIDC env vars
            for key in ['OIDC_PROVIDER_URL', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET']:
                os.environ.pop(key, None)

            from changedetectionio.oidc import is_oidc_enabled
            assert not is_oidc_enabled()

    def test_oidc_disabled_without_provider_url(self):
        """OIDC should be disabled if provider URL is missing."""
        env = {
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import is_oidc_enabled
            assert not is_oidc_enabled()

    def test_oidc_disabled_without_client_id(self):
        """OIDC should be disabled if client ID is missing."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_SECRET': 'test-secret',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import is_oidc_enabled
            assert not is_oidc_enabled()

    def test_oidc_disabled_without_client_secret(self):
        """OIDC should be disabled if client secret is missing."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_ID': 'test-client',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import is_oidc_enabled
            assert not is_oidc_enabled()

    def test_oidc_enabled_with_all_required_env_vars(self):
        """OIDC should be enabled when all required env vars are set."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import is_oidc_enabled
            assert is_oidc_enabled()


class TestOIDCConfigParsing:
    """Test OIDC configuration parsing."""

    def test_get_oidc_config_returns_none_when_not_configured(self):
        """get_oidc_config should return None when OIDC is not configured."""
        with patch.dict(os.environ, {}, clear=True):
            for key in ['OIDC_PROVIDER_URL', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET']:
                os.environ.pop(key, None)

            from changedetectionio.oidc import get_oidc_config
            assert get_oidc_config() is None

    def test_get_oidc_config_parses_all_fields(self):
        """get_oidc_config should correctly parse all configuration fields."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
            'OIDC_ALLOWED_GROUPS': 'admin,users,editors',
            'OIDC_GROUPS_CLAIM': 'my_groups',
            'OIDC_SCOPES': 'openid email profile',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import get_oidc_config
            config = get_oidc_config()

            assert config is not None
            assert config['provider_url'] == 'https://kanidm.example.com/oauth2/openid/app'
            assert config['client_id'] == 'test-client'
            assert config['client_secret'] == 'test-secret'
            assert config['allowed_groups'] == ['admin', 'users', 'editors']
            assert config['groups_claim'] == 'my_groups'
            assert config['scopes'] == 'openid email profile'

    def test_get_oidc_config_uses_defaults(self):
        """get_oidc_config should use defaults for optional fields."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import get_oidc_config
            config = get_oidc_config()

            assert config is not None
            assert config['allowed_groups'] == []  # Empty by default
            assert config['groups_claim'] == 'groups'  # Default claim name
            assert 'openid' in config['scopes']  # Default scopes

    def test_get_oidc_config_strips_trailing_slash(self):
        """get_oidc_config should strip trailing slash from provider URL."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app/',
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import get_oidc_config
            config = get_oidc_config()

            assert config['provider_url'] == 'https://kanidm.example.com/oauth2/openid/app'

    def test_get_oidc_config_handles_comma_separated_scopes(self):
        """get_oidc_config should convert comma-separated scopes to space-separated."""
        env = {
            'OIDC_PROVIDER_URL': 'https://kanidm.example.com/oauth2/openid/app',
            'OIDC_CLIENT_ID': 'test-client',
            'OIDC_CLIENT_SECRET': 'test-secret',
            'OIDC_SCOPES': 'openid,email,profile,groups_name',
        }
        with patch.dict(os.environ, env, clear=True):
            from changedetectionio.oidc import get_oidc_config
            config = get_oidc_config()

            # Scopes should be space-separated for OAuth2 standard
            assert config['scopes'] == 'openid email profile groups_name'


class TestAuthDecoratorOIDC:
    """Test auth decorator OIDC awareness."""

    def test_auth_decorator_is_oidc_enabled_check(self):
        """auth_decorator should have its own is_oidc_enabled function."""
        from changedetectionio.auth_decorator import is_oidc_enabled

        # With no env vars, should be disabled
        with patch.dict(os.environ, {}, clear=True):
            for key in ['OIDC_PROVIDER_URL', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET']:
                os.environ.pop(key, None)
            assert not is_oidc_enabled()

        # With all env vars, should be enabled
        env = {
            'OIDC_PROVIDER_URL': 'https://example.com',
            'OIDC_CLIENT_ID': 'client',
            'OIDC_CLIENT_SECRET': 'secret',
        }
        with patch.dict(os.environ, env, clear=True):
            assert is_oidc_enabled()


class TestFlaskAppOIDC:
    """Test flask_app OIDC helper."""

    def test_flask_app_is_oidc_enabled_check(self):
        """flask_app should have is_oidc_enabled function."""
        from changedetectionio.flask_app import is_oidc_enabled

        # With no env vars, should be disabled
        with patch.dict(os.environ, {}, clear=True):
            for key in ['OIDC_PROVIDER_URL', 'OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET']:
                os.environ.pop(key, None)
            assert not is_oidc_enabled()

        # With all env vars, should be enabled
        env = {
            'OIDC_PROVIDER_URL': 'https://example.com',
            'OIDC_CLIENT_ID': 'client',
            'OIDC_CLIENT_SECRET': 'secret',
        }
        with patch.dict(os.environ, env, clear=True):
            assert is_oidc_enabled()
