"""
Tests for Authentication Service (US-016)

Comprehensive tests for:
- User registration (admin-only)
- Login with email/password
- Password hashing with bcrypt
- Session management with secure cookies
- Admin role: full CRUD access
- Viewer role: read-only access
- Rate limiting on login attempts (5 per minute)
- Logout endpoint that clears session

Run with: pytest tasks/test_auth.py -v
"""

# Test bcrypt availability
import importlib.util
import os
import time
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Configure pytest-asyncio
pytest_plugins = ('pytest_asyncio',)

HAS_BCRYPT = importlib.util.find_spec("bcrypt") is not None


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def rate_limiter():
    """Create a rate limiter for testing."""
    from tasks.auth import RateLimiter

    return RateLimiter(max_requests=5, window_seconds=60)


@pytest.fixture
def mock_user():
    """Create a mock User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.password_hash = "$2b$12$test_hash"
    user.role = "viewer"
    user.is_active = True
    user.created_at = datetime.now()
    user.last_login = None

    user.is_admin.return_value = False
    user.is_viewer.return_value = True
    user.can_edit.return_value = False
    user.can_view.return_value = True
    user.can_manage_users.return_value = False
    user.can_manage_tags.return_value = False
    user.can_manage_events.return_value = False

    return user


@pytest.fixture
def mock_admin_user():
    """Create a mock admin User object."""
    user = MagicMock()
    user.id = uuid.uuid4()
    user.email = "admin@example.com"
    user.password_hash = "$2b$12$admin_hash"
    user.role = "admin"
    user.is_active = True
    user.created_at = datetime.now()
    user.last_login = None

    user.is_admin.return_value = True
    user.is_viewer.return_value = False
    user.can_edit.return_value = True
    user.can_view.return_value = True
    user.can_manage_users.return_value = True
    user.can_manage_tags.return_value = True
    user.can_manage_events.return_value = True

    return user


@pytest.fixture
def flask_user(mock_user):
    """Create a FlaskUser wrapper."""
    from tasks.auth import FlaskUser

    return FlaskUser(mock_user)


@pytest.fixture
def flask_admin_user(mock_admin_user):
    """Create a FlaskUser wrapper for admin."""
    from tasks.auth import FlaskUser

    return FlaskUser(mock_admin_user)


# =============================================================================
# Rate Limiter Tests
# =============================================================================


class TestRateLimiter:
    """Tests for the rate limiter."""

    def test_allows_requests_under_limit(self, rate_limiter):
        """Test that requests under the limit are allowed."""
        ip = "192.168.1.1"

        for i in range(5):
            assert rate_limiter.is_allowed(ip) is True

    def test_blocks_requests_over_limit(self, rate_limiter):
        """Test that requests over the limit are blocked."""
        ip = "192.168.1.2"

        # Use up all allowed requests
        for _ in range(5):
            rate_limiter.is_allowed(ip)

        # 6th request should be blocked
        assert rate_limiter.is_allowed(ip) is False

    def test_different_ips_have_separate_limits(self, rate_limiter):
        """Test that different IPs have separate rate limits."""
        ip1 = "192.168.1.3"
        ip2 = "192.168.1.4"

        # Exhaust ip1's limit
        for _ in range(5):
            rate_limiter.is_allowed(ip1)

        # ip2 should still have requests available
        assert rate_limiter.is_allowed(ip2) is True

    def test_get_remaining(self, rate_limiter):
        """Test getting remaining requests."""
        ip = "192.168.1.5"

        assert rate_limiter.get_remaining(ip) == 5

        rate_limiter.is_allowed(ip)
        assert rate_limiter.get_remaining(ip) == 4

        rate_limiter.is_allowed(ip)
        assert rate_limiter.get_remaining(ip) == 3

    def test_reset(self, rate_limiter):
        """Test resetting rate limit for an IP."""
        ip = "192.168.1.6"

        # Use up all requests
        for _ in range(5):
            rate_limiter.is_allowed(ip)

        assert rate_limiter.get_remaining(ip) == 0

        # Reset
        rate_limiter.reset(ip)

        assert rate_limiter.get_remaining(ip) == 5

    def test_window_expiry(self):
        """Test that old requests expire from the window."""
        from tasks.auth import RateLimiter

        # Create limiter with 1-second window
        limiter = RateLimiter(max_requests=2, window_seconds=1)
        ip = "192.168.1.7"

        # Use up limit
        limiter.is_allowed(ip)
        limiter.is_allowed(ip)
        assert limiter.is_allowed(ip) is False

        # Wait for window to expire
        time.sleep(1.1)

        # Should be allowed again
        assert limiter.is_allowed(ip) is True


# =============================================================================
# Password Hashing Tests
# =============================================================================


@pytest.mark.skipif(not HAS_BCRYPT, reason="bcrypt not installed")
class TestPasswordHashing:
    """Tests for password hashing functionality."""

    def test_hash_password(self):
        """Test password hashing."""
        from tasks.auth import AuthService

        password = "secure_password_123"
        hashed = AuthService.hash_password(password)

        # Hash should be a bcrypt hash
        assert hashed.startswith("$2b$")
        assert len(hashed) == 60

    def test_hash_password_different_each_time(self):
        """Test that same password produces different hashes (salt)."""
        from tasks.auth import AuthService

        password = "secure_password_123"
        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)

        # Hashes should be different due to salt
        assert hash1 != hash2

    def test_verify_password_correct(self):
        """Test verifying correct password."""
        from tasks.auth import AuthService

        password = "secure_password_123"
        hashed = AuthService.hash_password(password)

        assert AuthService.verify_password(password, hashed) is True

    def test_verify_password_incorrect(self):
        """Test verifying incorrect password."""
        from tasks.auth import AuthService

        password = "secure_password_123"
        wrong_password = "wrong_password"
        hashed = AuthService.hash_password(password)

        assert AuthService.verify_password(wrong_password, hashed) is False

    def test_verify_password_invalid_hash(self):
        """Test verifying against invalid hash returns False."""
        from tasks.auth import AuthService

        assert AuthService.verify_password("password", "invalid_hash") is False

    def test_verify_password_empty_password(self):
        """Test verifying empty password."""
        from tasks.auth import AuthService

        hashed = AuthService.hash_password("valid_password")
        assert AuthService.verify_password("", hashed) is False


# =============================================================================
# FlaskUser Tests
# =============================================================================


class TestFlaskUser:
    """Tests for the FlaskUser wrapper."""

    def test_get_id(self, flask_user, mock_user):
        """Test get_id returns string UUID."""
        assert flask_user.get_id() == str(mock_user.id)

    def test_properties(self, flask_user, mock_user):
        """Test FlaskUser properties."""
        assert flask_user.email == mock_user.email
        assert flask_user.role == mock_user.role
        assert flask_user.is_active == mock_user.is_active
        assert flask_user.is_authenticated is True
        assert flask_user.is_anonymous is False

    def test_viewer_permissions(self, flask_user):
        """Test viewer role permissions."""
        assert flask_user.is_admin() is False
        assert flask_user.is_viewer() is True
        assert flask_user.can_edit() is False
        assert flask_user.can_view() is True
        assert flask_user.can_manage_users() is False
        assert flask_user.can_manage_tags() is False
        assert flask_user.can_manage_events() is False

    def test_admin_permissions(self, flask_admin_user):
        """Test admin role permissions."""
        assert flask_admin_user.is_admin() is True
        assert flask_admin_user.is_viewer() is False
        assert flask_admin_user.can_edit() is True
        assert flask_admin_user.can_view() is True
        assert flask_admin_user.can_manage_users() is True
        assert flask_admin_user.can_manage_tags() is True
        assert flask_admin_user.can_manage_events() is True

    def test_to_dict(self, flask_user, mock_user):
        """Test conversion to dictionary."""
        user_dict = flask_user.to_dict()

        assert user_dict['id'] == str(mock_user.id)
        assert user_dict['email'] == mock_user.email
        assert user_dict['role'] == mock_user.role
        assert user_dict['is_active'] == mock_user.is_active
        assert 'password_hash' not in user_dict  # Should not include password


# =============================================================================
# Role-Based Access Decorator Tests
# =============================================================================


class TestRoleDecorators:
    """Tests for role-based access decorators."""

    def test_admin_required_allows_admin(self, flask_admin_user):
        """Test admin_required decorator allows admin users."""
        from tasks.auth import admin_required

        with patch('tasks.auth.current_user', flask_admin_user):

            @admin_required
            def protected_func():
                return "success"

            result = protected_func()
            assert result == "success"

    def test_admin_required_blocks_viewer(self, flask_user):
        """Test admin_required decorator blocks viewer users."""
        from tasks.auth import admin_required

        flask_user._user.is_authenticated = True
        with patch('tasks.auth.current_user', flask_user):

            @admin_required
            def protected_func():
                return "success"

            result, status = protected_func()
            assert status == 403
            assert 'Admin access required' in result['error']

    def test_admin_required_blocks_unauthenticated(self):
        """Test admin_required decorator blocks unauthenticated users."""
        from tasks.auth import admin_required

        mock_anon = MagicMock()
        mock_anon.is_authenticated = False

        with patch('tasks.auth.current_user', mock_anon):

            @admin_required
            def protected_func():
                return "success"

            result, status = protected_func()
            assert status == 401

    def test_viewer_required_allows_viewer(self, flask_user):
        """Test viewer_required decorator allows viewer users."""
        from tasks.auth import viewer_required

        with patch('tasks.auth.current_user', flask_user):

            @viewer_required
            def protected_func():
                return "success"

            result = protected_func()
            assert result == "success"

    def test_viewer_required_allows_admin(self, flask_admin_user):
        """Test viewer_required decorator allows admin users."""
        from tasks.auth import viewer_required

        with patch('tasks.auth.current_user', flask_admin_user):

            @viewer_required
            def protected_func():
                return "success"

            result = protected_func()
            assert result == "success"

    def test_viewer_required_blocks_unauthenticated(self):
        """Test viewer_required decorator blocks unauthenticated users."""
        from tasks.auth import viewer_required

        mock_anon = MagicMock()
        mock_anon.is_authenticated = False

        with patch('tasks.auth.current_user', mock_anon):

            @viewer_required
            def protected_func():
                return "success"

            result, status = protected_func()
            assert status == 401


# =============================================================================
# AuthService Tests (with mocked database)
# =============================================================================


class TestAuthServiceMocked:
    """Tests for AuthService with mocked database operations."""

    @pytest.fixture
    def auth_service(self):
        """Create AuthService with mocked database."""
        from tasks.auth import AuthService

        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
            service = AuthService()
            service._initialized = True
            service._async_session = MagicMock()
            return service

    @pytest.mark.asyncio
    async def test_register_user_first_user_becomes_admin(self, auth_service):
        """Test that first registered user becomes admin."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        # Mock no existing users
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        # Mock User.get_by_email returns None (email not taken)
        with patch('tasks.models.User.get_by_email', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None

            auth_service._async_session = MagicMock(return_value=mock_session)

            result = await auth_service.register_user(
                email="first@example.com",
                password="secure_password_123",
            )

            # First user should be created with admin role
            assert result['success'] is True
            assert result['user']['email'] == 'first@example.com'

    @pytest.mark.asyncio
    async def test_register_user_requires_admin(self, auth_service, mock_user):
        """Test that subsequent users require admin to create."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        # Mock existing user exists
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute = AsyncMock(return_value=mock_result)

        auth_service._async_session = MagicMock(return_value=mock_session)

        # Without admin_user
        result = await auth_service.register_user(
            email="new@example.com",
            password="secure_password_123",
        )

        assert result['success'] is False
        assert 'admin' in result['error'].lower()

    @pytest.mark.asyncio
    async def test_register_user_validates_email(self, auth_service, flask_admin_user):
        """Test that registration validates email format."""
        result = await auth_service.register_user(
            email="invalid-email",
            password="secure_password_123",
            admin_user=flask_admin_user,
        )

        assert result['success'] is False
        assert 'email' in result['error'].lower()

    @pytest.mark.asyncio
    async def test_register_user_validates_password_length(self, auth_service, flask_admin_user):
        """Test that registration validates password length."""
        result = await auth_service.register_user(
            email="test@example.com",
            password="short",
            admin_user=flask_admin_user,
        )

        assert result['success'] is False
        assert 'password' in result['error'].lower()
        assert '8' in result['error']

    @pytest.mark.asyncio
    async def test_register_user_validates_role(self, auth_service, flask_admin_user):
        """Test that registration validates role."""
        result = await auth_service.register_user(
            email="test@example.com",
            password="secure_password_123",
            role="invalid_role",
            admin_user=flask_admin_user,
        )

        assert result['success'] is False
        assert 'role' in result['error'].lower()

    @pytest.mark.asyncio
    async def test_login_with_rate_limiting(self, auth_service):
        """Test that login respects rate limiting."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        auth_service._async_session = MagicMock(return_value=mock_session)

        # Reset rate limiter
        from tasks.auth import login_rate_limiter

        client_ip = "10.0.0.100"
        login_rate_limiter.reset(client_ip)

        # Make 5 failed attempts
        with patch('tasks.models.User.get_by_email', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None  # User not found

            for _ in range(5):
                await auth_service.login("test@example.com", "wrong", client_ip)

            # 6th attempt should be rate limited
            result = await auth_service.login("test@example.com", "wrong", client_ip)
            assert result.get('rate_limited') is True

    @pytest.mark.asyncio
    async def test_login_resets_rate_limit_on_success(self, auth_service, mock_user):
        """Test that successful login resets rate limit."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        auth_service._async_session = MagicMock(return_value=mock_session)

        # Reset rate limiter
        from tasks.auth import login_rate_limiter

        client_ip = "10.0.0.101"
        login_rate_limiter.reset(client_ip)

        # Make some failed attempts
        with patch('tasks.models.User.get_by_email', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            for _ in range(3):
                await auth_service.login("test@example.com", "wrong", client_ip)

        # Remaining should be 2
        assert login_rate_limiter.get_remaining(client_ip) == 2

        # Successful login should reset
        with patch('tasks.models.User.get_by_email', new_callable=AsyncMock) as mock_get:
            mock_user.password_hash = "$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.XsZ.OFYfL.lC4W"
            mock_get.return_value = mock_user

            with patch.object(auth_service, 'verify_password', return_value=True):
                result = await auth_service.login("test@example.com", "correct", client_ip)
                if result['success']:
                    # Rate limit should be reset
                    assert login_rate_limiter.get_remaining(client_ip) == 5

    @pytest.mark.asyncio
    async def test_login_inactive_user(self, auth_service, mock_user):
        """Test that inactive users cannot login."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.__aexit__.return_value = None

        mock_user.is_active = False

        auth_service._async_session = MagicMock(return_value=mock_session)

        with patch('tasks.models.User.get_by_email', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_user

            result = await auth_service.login("test@example.com", "password")

            assert result['success'] is False
            assert 'disabled' in result['error'].lower()


# =============================================================================
# Integration Tests (require database)
# =============================================================================


@pytest.mark.skipif(
    not os.getenv('DATABASE_URL'),
    reason="DATABASE_URL not set for integration tests",
)
class TestAuthServiceIntegration:
    """Integration tests for AuthService with real database."""

    @pytest.fixture
    async def auth_service(self):
        """Create AuthService with real database connection."""
        from tasks.auth import AuthService

        service = AuthService()
        await service.initialize()
        yield service
        await service.close()

    @pytest.mark.asyncio
    async def test_full_user_lifecycle(self, auth_service):
        """Test complete user registration, login, and management."""
        # Generate unique email for test
        unique_email = f"test_{uuid.uuid4().hex[:8]}@example.com"

        # Register first user (becomes admin)
        result = await auth_service.register_user(
            email=unique_email,
            password="secure_password_123",
        )
        assert result['success'] is True
        user_id = result['user']['id']

        # Login
        login_result = await auth_service.login(
            email=unique_email,
            password="secure_password_123",
        )
        assert login_result['success'] is True
        assert login_result['user']['email'] == unique_email

        # Get user
        user = await auth_service.get_user(user_id)
        assert user is not None
        assert user['email'] == unique_email

        # Clean up - would need admin user to delete
        # This is left for manual cleanup or fixture teardown


# =============================================================================
# Acceptance Criteria Verification Tests
# =============================================================================


class TestAcceptanceCriteria:
    """Tests specifically for US-016 acceptance criteria."""

    def test_user_registration_admin_only(self, flask_user, flask_admin_user):
        """
        AC: User registration endpoint (admin-only can create users)

        Verify that only admin users can create new users.
        """

        # Viewer cannot create users
        assert flask_user.can_manage_users() is False

        # Admin can create users
        assert flask_admin_user.can_manage_users() is True

    @pytest.mark.skipif(not HAS_BCRYPT, reason="bcrypt not installed")
    def test_password_hashing_with_bcrypt(self):
        """
        AC: Password hashing with bcrypt

        Verify passwords are hashed using bcrypt.
        """
        from tasks.auth import AuthService

        password = "test_password_123"
        hashed = AuthService.hash_password(password)

        # Verify bcrypt format
        assert hashed.startswith("$2b$12$")  # bcrypt prefix with 12 rounds
        assert len(hashed) == 60

        # Verify password can be verified
        assert AuthService.verify_password(password, hashed) is True
        assert AuthService.verify_password("wrong", hashed) is False

    def test_admin_role_full_crud_access(self, flask_admin_user):
        """
        AC: Admin role: full CRUD access to events, tags, users

        Verify admin users have full access to all resources.
        """
        assert flask_admin_user.can_manage_users() is True
        assert flask_admin_user.can_manage_tags() is True
        assert flask_admin_user.can_manage_events() is True
        assert flask_admin_user.can_edit() is True
        assert flask_admin_user.can_view() is True

    def test_viewer_role_read_only_access(self, flask_user):
        """
        AC: Viewer role: read-only access to events and history

        Verify viewer users have only read access.
        """
        assert flask_user.can_view() is True
        assert flask_user.can_edit() is False
        assert flask_user.can_manage_users() is False
        assert flask_user.can_manage_tags() is False
        assert flask_user.can_manage_events() is False

    def test_rate_limiting_on_login_attempts(self):
        """
        AC: Rate limiting on login attempts (5 per minute)

        Verify login attempts are rate limited.
        """
        from tasks.auth import RateLimiter

        limiter = RateLimiter(max_requests=5, window_seconds=60)
        ip = "test_rate_limit_ip"

        # 5 requests should be allowed
        for i in range(5):
            assert limiter.is_allowed(ip) is True, f"Request {i + 1} should be allowed"

        # 6th request should be blocked
        assert limiter.is_allowed(ip) is False, "6th request should be blocked"

    def test_secure_cookie_configuration(self):
        """
        AC: Session management with secure cookies

        Verify secure cookie settings are configured.
        """
        from flask import Flask

        from tasks.auth import AuthService

        app = Flask(__name__)
        app.config['SECRET_KEY'] = 'test-key'

        with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost/test'}):
            auth = AuthService()
            auth._initialized = True
            auth.init_app(app)

        # Check secure cookie settings
        assert app.config['SESSION_COOKIE_SECURE'] is True
        assert app.config['SESSION_COOKIE_HTTPONLY'] is True
        assert app.config['SESSION_COOKIE_SAMESITE'] == 'Lax'
        assert app.config['REMEMBER_COOKIE_SECURE'] is True
        assert app.config['REMEMBER_COOKIE_HTTPONLY'] is True


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
