"""
Authentication Service for ATC Page Monitor

This module provides user authentication and session management with:
- Password hashing with bcrypt
- Session management with secure cookies
- Role-based access control (admin/viewer)
- Rate limiting on login attempts (5 per minute)

Usage:
    from tasks.auth import AuthService, get_auth_service

    auth = get_auth_service()

    # Register a new user (admin only)
    user = await auth.register_user(email, password, role='viewer', admin_user=current_user)

    # Login
    user = await auth.login(email, password, request)

    # Check permissions
    if auth.can_access(current_user, 'edit'):
        # Allow edit operation
"""

import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from functools import wraps
from threading import Lock
from typing import Any

import bcrypt
from flask_login import LoginManager, UserMixin, current_user
from sqlalchemy import select

from tasks.models import User, UserRole, async_session_factory, create_async_engine_from_url

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiter
# =============================================================================


class RateLimiter:
    """
    Simple in-memory rate limiter for login attempts.

    Implements a sliding window rate limit of 5 requests per minute per IP.
    """

    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed per window
            window_seconds: Time window in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        """
        Check if request is allowed for the given key (e.g., IP address).

        Args:
            key: Identifier for rate limiting (usually IP address)

        Returns:
            True if request is allowed, False if rate limited
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            # Clean old requests
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]

            # Check if under limit
            if len(self._requests[key]) >= self.max_requests:
                return False

            # Record this request
            self._requests[key].append(now)
            return True

    def get_remaining(self, key: str) -> int:
        """Get remaining requests for key."""
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            self._requests[key] = [t for t in self._requests[key] if t > cutoff]
            return max(0, self.max_requests - len(self._requests[key]))

    def reset(self, key: str) -> None:
        """Reset rate limit for key."""
        with self._lock:
            self._requests[key] = []


# Global rate limiter for login attempts
login_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)


# =============================================================================
# Flask-Login User Wrapper
# =============================================================================


class FlaskUser(UserMixin):
    """
    Flask-Login compatible user wrapper.

    Wraps the SQLAlchemy User model to work with Flask-Login.
    """

    def __init__(self, user: User):
        """
        Initialize Flask user wrapper.

        Args:
            user: SQLAlchemy User model instance
        """
        self._user = user

    def get_id(self) -> str:
        """Return user ID as string (required by Flask-Login)."""
        return str(self._user.id)

    @property
    def id(self) -> uuid.UUID:
        """Return user UUID."""
        return self._user.id

    @property
    def email(self) -> str:
        """Return user email."""
        return self._user.email

    @property
    def role(self) -> str:
        """Return user role."""
        return self._user.role

    @property
    def is_active(self) -> bool:
        """Return whether user is active."""
        return self._user.is_active

    @property
    def is_authenticated(self) -> bool:
        """Return whether user is authenticated."""
        return True

    @property
    def is_anonymous(self) -> bool:
        """Return whether user is anonymous."""
        return False

    @property
    def created_at(self) -> datetime | None:
        """Return user creation timestamp."""
        return self._user.created_at

    @property
    def last_login(self) -> datetime | None:
        """Return last login timestamp."""
        return self._user.last_login

    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self._user.is_admin()

    def is_viewer(self) -> bool:
        """Check if user has viewer role."""
        return self._user.is_viewer()

    def can_edit(self) -> bool:
        """Check if user can edit resources (admin only)."""
        return self._user.can_edit()

    def can_view(self) -> bool:
        """Check if user can view resources (all active users)."""
        return self._user.can_view()

    def can_manage_users(self) -> bool:
        """Check if user can manage other users (admin only)."""
        return self._user.can_manage_users()

    def can_manage_tags(self) -> bool:
        """Check if user can create/edit tags (admin only)."""
        return self._user.can_manage_tags()

    def can_manage_events(self) -> bool:
        """Check if user can create/edit events (admin only)."""
        return self._user.can_manage_events()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (excludes password_hash)."""
        return {
            'id': str(self._user.id),
            'email': self._user.email,
            'role': self._user.role,
            'is_active': self._user.is_active,
            'created_at': self._user.created_at.isoformat() if self._user.created_at else None,
            'last_login': self._user.last_login.isoformat() if self._user.last_login else None,
        }


# =============================================================================
# Authentication Service
# =============================================================================


class AuthService:
    """
    Core authentication service for the application.

    Provides:
    - User registration (admin-only)
    - Login with email/password
    - Password hashing with bcrypt
    - Session management
    - Role-based access control
    """

    def __init__(self, database_url: str | None = None):
        """
        Initialize authentication service.

        Args:
            database_url: PostgreSQL connection URL. If not provided,
                         reads from DATABASE_URL environment variable.
        """
        import os

        self.database_url = database_url or os.getenv('DATABASE_URL')
        if not self.database_url:
            raise ValueError("DATABASE_URL must be provided or set as environment variable")

        self._engine = None
        self._async_session = None
        self._initialized = False
        self._login_manager: LoginManager | None = None

    async def initialize(self) -> None:
        """Initialize the database connection."""
        if self._initialized:
            return

        self._engine = create_async_engine_from_url(self.database_url)
        self._async_session = async_session_factory(self._engine)
        self._initialized = True
        logger.info("AuthService initialized")

    async def close(self) -> None:
        """Close database connections."""
        if self._engine:
            await self._engine.dispose()
            self._engine = None
            self._async_session = None
            self._initialized = False

    def init_app(self, app) -> None:
        """
        Initialize Flask-Login with the Flask app.

        Args:
            app: Flask application instance
        """
        self._login_manager = LoginManager()
        self._login_manager.init_app(app)
        self._login_manager.login_view = 'auth.login'
        self._login_manager.login_message = 'Please log in to access this page.'

        # Configure secure session cookies
        # Note: These settings are recommended for production.
        # In development with HTTP, SESSION_COOKIE_SECURE may need to be False.
        app.config['SESSION_COOKIE_SECURE'] = True
        app.config['SESSION_COOKIE_HTTPONLY'] = True
        app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
        app.config['REMEMBER_COOKIE_SECURE'] = True
        app.config['REMEMBER_COOKIE_HTTPONLY'] = True

        # User loader for Flask-Login
        @self._login_manager.user_loader
        def load_user(user_id: str) -> FlaskUser | None:
            """Load user by ID for Flask-Login."""
            import asyncio

            try:
                # Run async user lookup in sync context
                loop = asyncio.new_event_loop()
                user = loop.run_until_complete(self._get_user_by_id_async(user_id))
                loop.close()
                if user and user.is_active:
                    return FlaskUser(user)
            except Exception as e:
                logger.error(f"Error loading user {user_id}: {e}")
            return None

    async def _get_user_by_id_async(self, user_id: str) -> User | None:
        """Get user by ID asynchronously."""
        if not self._async_session:
            return None

        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return None

        async with self._async_session() as session:
            return await User.get_by_id(session, user_uuid)

    # -------------------------------------------------------------------------
    # Password Hashing
    # -------------------------------------------------------------------------

    @staticmethod
    def hash_password(password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Bcrypt hashed password
        """
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            password: Plain text password to verify
            password_hash: Bcrypt hashed password

        Returns:
            True if password matches, False otherwise
        """
        try:
            return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # User Registration (Admin Only)
    # -------------------------------------------------------------------------

    async def register_user(
        self,
        email: str,
        password: str,
        role: str = UserRole.VIEWER.value,
        admin_user: FlaskUser | None = None,
    ) -> dict[str, Any]:
        """
        Register a new user (admin only operation).

        Args:
            email: User email address (must be unique)
            password: Plain text password (will be hashed)
            role: User role ('admin' or 'viewer', default: 'viewer')
            admin_user: The admin user performing the registration

        Returns:
            Dict with 'success', 'user' (if successful), or 'error' message

        Raises:
            PermissionError: If admin_user is not an admin
        """
        # Validate admin permission
        if admin_user is None:
            # Allow first user registration without admin
            async with self._async_session() as session:
                result = await session.execute(select(User).limit(1))
                existing_user = result.scalar_one_or_none()
                if existing_user:
                    return {'success': False, 'error': 'Admin user required for registration'}
                # First user - force admin role
                role = UserRole.ADMIN.value
        elif not admin_user.can_manage_users():
            return {'success': False, 'error': 'Only admins can create users'}

        # Validate email
        email = email.strip().lower()
        if not email or '@' not in email:
            return {'success': False, 'error': 'Invalid email address'}

        # Validate password
        if len(password) < 8:
            return {'success': False, 'error': 'Password must be at least 8 characters'}

        # Validate role
        if role not in [UserRole.ADMIN.value, UserRole.VIEWER.value]:
            return {'success': False, 'error': 'Invalid role. Must be admin or viewer'}

        async with self._async_session() as session:
            # Check if email already exists
            existing = await User.get_by_email(session, email)
            if existing:
                return {'success': False, 'error': 'Email already registered'}

            # Create user
            password_hash = self.hash_password(password)
            user = User(
                email=email,
                password_hash=password_hash,
                role=role,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

            logger.info(f"User registered: {email} with role {role}")

            return {
                'success': True,
                'user': {
                    'id': str(user.id),
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active,
                    'created_at': user.created_at.isoformat() if user.created_at else None,
                },
            }

    # -------------------------------------------------------------------------
    # Login/Logout
    # -------------------------------------------------------------------------

    async def login(
        self, email: str, password: str, client_ip: str | None = None
    ) -> dict[str, Any]:
        """
        Authenticate a user with email and password.

        Implements rate limiting of 5 attempts per minute per IP.

        Args:
            email: User email address
            password: Plain text password
            client_ip: Client IP address for rate limiting

        Returns:
            Dict with 'success', 'user' (if successful), or 'error' message
        """
        # Rate limiting
        if client_ip:
            if not login_rate_limiter.is_allowed(client_ip):
                remaining_wait = login_rate_limiter.window_seconds
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return {
                    'success': False,
                    'error': f'Too many login attempts. Please wait {remaining_wait} seconds.',
                    'rate_limited': True,
                }

        email = email.strip().lower()

        async with self._async_session() as session:
            user = await User.get_by_email(session, email)

            if not user:
                logger.warning(f"Login failed: user not found - {email}")
                return {'success': False, 'error': 'Invalid email or password'}

            if not user.is_active:
                logger.warning(f"Login failed: account disabled - {email}")
                return {'success': False, 'error': 'Account is disabled'}

            if not self.verify_password(password, user.password_hash):
                logger.warning(f"Login failed: invalid password - {email}")
                return {'success': False, 'error': 'Invalid email or password'}

            # Update last login
            user.last_login = datetime.now(timezone.utc)
            await session.commit()

            # Reset rate limit on successful login
            if client_ip:
                login_rate_limiter.reset(client_ip)

            logger.info(f"User logged in: {email}")

            return {
                'success': True,
                'user': {
                    'id': str(user.id),
                    'email': user.email,
                    'role': user.role,
                    'is_active': user.is_active,
                    'last_login': user.last_login.isoformat() if user.last_login else None,
                },
            }

    async def get_user_for_login(self, email: str) -> User | None:
        """
        Get user by email for Flask-Login session.

        Args:
            email: User email

        Returns:
            User model instance or None
        """
        async with self._async_session() as session:
            return await User.get_by_email(session, email)

    # -------------------------------------------------------------------------
    # User Management
    # -------------------------------------------------------------------------

    async def get_user(self, user_id: str) -> dict[str, Any] | None:
        """
        Get user by ID.

        Args:
            user_id: User UUID string

        Returns:
            User dict or None
        """
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return None

        async with self._async_session() as session:
            user = await User.get_by_id(session, user_uuid)
            if user:
                return FlaskUser(user).to_dict()
        return None

    async def get_all_users(self) -> list[dict[str, Any]]:
        """
        Get all users (admin only operation).

        Returns:
            List of user dicts
        """
        async with self._async_session() as session:
            result = await session.execute(select(User).order_by(User.email))
            users = result.scalars().all()
            return [FlaskUser(u).to_dict() for u in users]

    async def update_user(
        self,
        user_id: str,
        updates: dict[str, Any],
        admin_user: FlaskUser | None = None,
    ) -> dict[str, Any]:
        """
        Update user properties.

        Args:
            user_id: User UUID string
            updates: Dict of fields to update (email, role, is_active, password)
            admin_user: Admin user performing the update

        Returns:
            Dict with 'success' and 'user' or 'error'
        """
        if not admin_user or not admin_user.can_manage_users():
            return {'success': False, 'error': 'Only admins can update users'}

        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return {'success': False, 'error': 'Invalid user ID'}

        async with self._async_session() as session:
            user = await User.get_by_id(session, user_uuid)
            if not user:
                return {'success': False, 'error': 'User not found'}

            # Update allowed fields
            if 'email' in updates:
                email = updates['email'].strip().lower()
                if email != user.email:
                    # Check if new email is taken
                    existing = await User.get_by_email(session, email)
                    if existing:
                        return {'success': False, 'error': 'Email already in use'}
                    user.email = email

            if 'role' in updates:
                role = updates['role']
                if role in [UserRole.ADMIN.value, UserRole.VIEWER.value]:
                    user.role = role

            if 'is_active' in updates:
                user.is_active = bool(updates['is_active'])

            if 'password' in updates:
                password = updates['password']
                if len(password) >= 8:
                    user.password_hash = self.hash_password(password)

            await session.commit()
            await session.refresh(user)

            logger.info(f"User updated: {user.email}")

            return {'success': True, 'user': FlaskUser(user).to_dict()}

    async def delete_user(
        self, user_id: str, admin_user: FlaskUser | None = None
    ) -> dict[str, Any]:
        """
        Delete a user.

        Args:
            user_id: User UUID string
            admin_user: Admin user performing the deletion

        Returns:
            Dict with 'success' or 'error'
        """
        if not admin_user or not admin_user.can_manage_users():
            return {'success': False, 'error': 'Only admins can delete users'}

        # Prevent self-deletion
        if str(admin_user.id) == user_id:
            return {'success': False, 'error': 'Cannot delete your own account'}

        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return {'success': False, 'error': 'Invalid user ID'}

        async with self._async_session() as session:
            user = await User.get_by_id(session, user_uuid)
            if not user:
                return {'success': False, 'error': 'User not found'}

            email = user.email
            await session.delete(user)
            await session.commit()

            logger.info(f"User deleted: {email}")

            return {'success': True}


# =============================================================================
# Role-Based Access Decorators
# =============================================================================


def login_required_async(f):
    """
    Decorator that requires user to be logged in.

    For async Flask routes.
    """

    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        return await f(*args, **kwargs)

    return decorated_function


def admin_required(f):
    """
    Decorator that requires user to have admin role.

    For sync Flask routes.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        if not current_user.is_admin():
            return {'error': 'Admin access required'}, 403
        return f(*args, **kwargs)

    return decorated_function


def admin_required_async(f):
    """
    Decorator that requires user to have admin role.

    For async Flask routes.
    """

    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        if not current_user.is_admin():
            return {'error': 'Admin access required'}, 403
        return await f(*args, **kwargs)

    return decorated_function


def viewer_required(f):
    """
    Decorator that requires user to have at least viewer role.

    Allows both admin and viewer access. For sync Flask routes.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        if not current_user.can_view():
            return {'error': 'Access denied'}, 403
        return f(*args, **kwargs)

    return decorated_function


def viewer_required_async(f):
    """
    Decorator that requires user to have at least viewer role.

    For async Flask routes.
    """

    @wraps(f)
    async def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return {'error': 'Authentication required'}, 401
        if not current_user.can_view():
            return {'error': 'Access denied'}, 403
        return await f(*args, **kwargs)

    return decorated_function


# =============================================================================
# Singleton Auth Service
# =============================================================================

_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    """
    Get the singleton AuthService instance.

    Returns:
        AuthService instance
    """
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


def set_auth_service(service: AuthService) -> None:
    """
    Set the AuthService instance (for testing).

    Args:
        service: AuthService instance
    """
    global _auth_service
    _auth_service = service


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import asyncio
    import os

    async def test_auth():
        """Test the authentication service."""
        database_url = os.getenv('DATABASE_URL')
        if not database_url:
            print("DATABASE_URL environment variable not set")
            return

        auth = AuthService(database_url=database_url)

        try:
            await auth.initialize()
            print("AuthService initialized")

            # Test password hashing
            password = "test_password_123"
            hashed = auth.hash_password(password)
            print(f"Password hashed: {hashed[:20]}...")

            # Verify password
            is_valid = auth.verify_password(password, hashed)
            print(f"Password verification: {is_valid}")

            # Verify wrong password fails
            is_invalid = auth.verify_password("wrong_password", hashed)
            print(f"Wrong password verification: {is_invalid}")

            # Test user registration (first user becomes admin)
            result = await auth.register_user(
                email="test@example.com",
                password="test_password_123",
            )
            print(f"Registration result: {result}")

            # Test login
            login_result = await auth.login(
                email="test@example.com",
                password="test_password_123",
                client_ip="127.0.0.1",
            )
            print(f"Login result: {login_result}")

            # Test rate limiting
            for i in range(6):
                result = await auth.login(
                    email="test@example.com",
                    password="wrong_password",
                    client_ip="192.168.1.100",
                )
                print(f"Login attempt {i + 1}: rate_limited={result.get('rate_limited', False)}")

            print("\nAll tests completed!")

        finally:
            await auth.close()

    asyncio.run(test_auth())
