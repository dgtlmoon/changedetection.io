"""
Authentication API Blueprint for ATC Page Monitor

This module provides Flask REST API endpoints for authentication:
- POST /api/v1/auth/register - Register a new user (admin-only)
- POST /api/v1/auth/login - Login with email/password
- POST /api/v1/auth/logout - Logout and clear session
- GET /api/v1/auth/me - Get current user info
- GET /api/v1/auth/users - List all users (admin-only)
- GET /api/v1/auth/users/<id> - Get user by ID (admin-only)
- PUT /api/v1/auth/users/<id> - Update user (admin-only)
- DELETE /api/v1/auth/users/<id> - Delete user (admin-only)

All endpoints return JSON responses.
Session management uses secure HTTP-only cookies.

Usage:
    from tasks.auth_api import construct_auth_blueprint

    app = Flask(__name__)
    auth_bp = construct_auth_blueprint(auth_service)
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
"""

import asyncio
import os
import uuid

from flask import Blueprint, current_app, jsonify, make_response, request, session
from flask_login import current_user, login_required, login_user, logout_user

from tasks.auth import (
    AuthService,
    FlaskUser,
    admin_required,
    get_auth_service,
    login_rate_limiter,
)

try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger(__name__)


def run_async(coro):
    """Run async coroutine in sync context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def construct_auth_blueprint(auth_service: AuthService | None = None) -> Blueprint:  # noqa: C901
    """
    Construct the authentication API blueprint.

    Args:
        auth_service: AuthService instance. If not provided, uses singleton.

    Returns:
        Flask Blueprint with auth routes
    """
    bp = Blueprint('auth', __name__)
    auth = auth_service or get_auth_service()

    def get_client_ip() -> str:
        """Get client IP address from request, handling proxies."""
        # Check for X-Forwarded-For header (when behind proxy)
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            # Take the first IP in the chain (original client)
            return forwarded.split(',')[0].strip()
        return request.remote_addr or 'unknown'

    # -------------------------------------------------------------------------
    # User Registration (Admin Only)
    # -------------------------------------------------------------------------

    @bp.route('/register', methods=['POST'])
    def register():
        """
        Register a new user.

        Only admins can create new users, unless this is the first user.

        Request JSON:
            {
                "email": "user@example.com",
                "password": "secure_password",
                "role": "viewer"  # or "admin", default is "viewer"
            }

        Returns:
            201: User created successfully
            400: Invalid request data
            401: Not authenticated
            403: Not authorized (not admin)
            409: Email already exists
        """
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body required'}), 400

        email = data.get('email', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'viewer')

        if not email:
            return jsonify({'error': 'Email is required'}), 400
        if not password:
            return jsonify({'error': 'Password is required'}), 400

        # Get current user if authenticated
        admin_user = None
        if current_user.is_authenticated:
            admin_user = current_user

        result = run_async(auth.register_user(
            email=email,
            password=password,
            role=role,
            admin_user=admin_user,
        ))

        if result['success']:
            logger.info(f"User registered via API: {email}")
            return jsonify(result['user']), 201
        else:
            error = result['error']
            if 'already registered' in error.lower():
                return jsonify({'error': error}), 409
            elif 'admin' in error.lower() or 'only admins' in error.lower():
                return jsonify({'error': error}), 403
            else:
                return jsonify({'error': error}), 400

    # -------------------------------------------------------------------------
    # Login
    # -------------------------------------------------------------------------

    @bp.route('/login', methods=['POST'])
    def login():
        """
        Login with email and password.

        Rate limited to 5 attempts per minute per IP.

        Request JSON:
            {
                "email": "user@example.com",
                "password": "secure_password",
                "remember": true  # optional, default false
            }

        Returns:
            200: Login successful, returns user info and sets session cookie
            400: Invalid request data
            401: Invalid credentials
            429: Rate limited
        """
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body required'}), 400

        email = data.get('email', '').strip()
        password = data.get('password', '')
        remember = data.get('remember', False)

        if not email:
            return jsonify({'error': 'Email is required'}), 400
        if not password:
            return jsonify({'error': 'Password is required'}), 400

        client_ip = get_client_ip()

        result = run_async(auth.login(
            email=email,
            password=password,
            client_ip=client_ip,
        ))

        if result.get('rate_limited'):
            response = jsonify({'error': result['error']})
            response.headers['Retry-After'] = str(login_rate_limiter.window_seconds)
            return response, 429

        if result['success']:
            # Get full user object for Flask-Login
            user = run_async(auth.get_user_for_login(email))
            if user:
                flask_user = FlaskUser(user)
                login_user(flask_user, remember=remember)

                logger.info(f"User logged in via API: {email}")

                # Build response with user info
                response = make_response(jsonify(result['user']))

                return response, 200

        return jsonify({'error': result.get('error', 'Login failed')}), 401

    # -------------------------------------------------------------------------
    # Logout
    # -------------------------------------------------------------------------

    @bp.route('/logout', methods=['POST'])
    @login_required
    def logout():
        """
        Logout and clear session.

        Clears the session cookie and invalidates the session.

        Returns:
            200: Logout successful
            401: Not authenticated
        """
        email = current_user.email if current_user.is_authenticated else 'unknown'
        logout_user()
        session.clear()

        logger.info(f"User logged out via API: {email}")

        response = make_response(jsonify({'message': 'Logged out successfully'}))
        # Clear session cookie
        response.delete_cookie(current_app.config.get('SESSION_COOKIE_NAME', 'session'))
        return response, 200

    # -------------------------------------------------------------------------
    # Current User
    # -------------------------------------------------------------------------

    @bp.route('/me', methods=['GET'])
    @login_required
    def get_current_user():
        """
        Get current authenticated user info.

        Returns:
            200: User info
            401: Not authenticated
        """
        return jsonify(current_user.to_dict()), 200

    # -------------------------------------------------------------------------
    # User Management (Admin Only)
    # -------------------------------------------------------------------------

    @bp.route('/users', methods=['GET'])
    @login_required
    @admin_required
    def list_users():
        """
        List all users (admin only).

        Returns:
            200: List of users
            401: Not authenticated
            403: Not authorized
        """
        users = run_async(auth.get_all_users())
        return jsonify({'users': users, 'total': len(users)}), 200

    @bp.route('/users/<user_id>', methods=['GET'])
    @login_required
    @admin_required
    def get_user(user_id: str):
        """
        Get user by ID (admin only).

        Returns:
            200: User info
            401: Not authenticated
            403: Not authorized
            404: User not found
        """
        # Validate UUID
        try:
            uuid.UUID(user_id)
        except ValueError:
            return jsonify({'error': 'Invalid user ID'}), 400

        user = run_async(auth.get_user(user_id))
        if user:
            return jsonify(user), 200
        return jsonify({'error': 'User not found'}), 404

    @bp.route('/users/<user_id>', methods=['PUT'])
    @login_required
    @admin_required
    def update_user(user_id: str):
        """
        Update user (admin only).

        Request JSON (all fields optional):
            {
                "email": "new@example.com",
                "password": "new_password",
                "role": "admin",
                "is_active": false
            }

        Returns:
            200: Updated user info
            400: Invalid request
            401: Not authenticated
            403: Not authorized
            404: User not found
        """
        # Validate UUID
        try:
            uuid.UUID(user_id)
        except ValueError:
            return jsonify({'error': 'Invalid user ID'}), 400

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body required'}), 400

        result = run_async(auth.update_user(
            user_id=user_id,
            updates=data,
            admin_user=current_user,
        ))

        if result['success']:
            logger.info(f"User updated via API: {user_id}")
            return jsonify(result['user']), 200
        else:
            error = result['error']
            if 'not found' in error.lower():
                return jsonify({'error': error}), 404
            elif 'admin' in error.lower():
                return jsonify({'error': error}), 403
            else:
                return jsonify({'error': error}), 400

    @bp.route('/users/<user_id>', methods=['DELETE'])
    @login_required
    @admin_required
    def delete_user(user_id: str):
        """
        Delete user (admin only).

        Returns:
            204: User deleted
            400: Invalid request (e.g., trying to delete self)
            401: Not authenticated
            403: Not authorized
            404: User not found
        """
        # Validate UUID
        try:
            uuid.UUID(user_id)
        except ValueError:
            return jsonify({'error': 'Invalid user ID'}), 400

        result = run_async(auth.delete_user(
            user_id=user_id,
            admin_user=current_user,
        ))

        if result['success']:
            logger.info(f"User deleted via API: {user_id}")
            return '', 204
        else:
            error = result['error']
            if 'not found' in error.lower():
                return jsonify({'error': error}), 404
            elif 'own account' in error.lower():
                return jsonify({'error': error}), 400
            elif 'admin' in error.lower():
                return jsonify({'error': error}), 403
            else:
                return jsonify({'error': error}), 400

    # -------------------------------------------------------------------------
    # Rate Limit Status (for debugging)
    # -------------------------------------------------------------------------

    @bp.route('/rate-limit-status', methods=['GET'])
    def rate_limit_status():
        """
        Get rate limit status for current IP.

        Returns remaining requests and window info.
        Useful for debugging and client-side rate limiting.

        Returns:
            200: Rate limit status
        """
        client_ip = get_client_ip()
        remaining = login_rate_limiter.get_remaining(client_ip)

        return jsonify({
            'remaining_requests': remaining,
            'max_requests': login_rate_limiter.max_requests,
            'window_seconds': login_rate_limiter.window_seconds,
        }), 200

    return bp


# =============================================================================
# Error Handlers
# =============================================================================


def register_auth_error_handlers(app):
    """
    Register authentication-related error handlers.

    Args:
        app: Flask application instance
    """

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({'error': 'Authentication required'}), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({'error': 'Access denied'}), 403


# =============================================================================
# CLI for Testing
# =============================================================================

if __name__ == "__main__":
    import os

    from flask import Flask

    # Create test app
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'test-secret-key-change-in-production'
    app.config['TESTING'] = True

    # Initialize auth service
    auth = AuthService(database_url=os.getenv('DATABASE_URL'))
    run_async(auth.initialize())
    auth.init_app(app)

    # Register blueprint
    auth_bp = construct_auth_blueprint(auth)
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    register_auth_error_handlers(app)

    # Print routes
    print("\nRegistered Auth Routes:")
    for rule in app.url_map.iter_rules():
        if 'auth' in rule.rule:
            print(f"  {rule.methods} {rule.rule}")

    # Run test server
    print("\nStarting test server on http://localhost:5001")
    print("Test endpoints:")
    print("  POST /api/v1/auth/register")
    print("  POST /api/v1/auth/login")
    print("  POST /api/v1/auth/logout")
    print("  GET  /api/v1/auth/me")
    print("  GET  /api/v1/auth/users")

    app.run(host='0.0.0.0', port=5001, debug=True)
