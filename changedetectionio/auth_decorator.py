import os
from functools import wraps

import flask_login
from flask import current_app, request
from flask_login import current_user


def is_oidc_enabled():
    """
    Check if OIDC authentication is configured via environment variables.

    Returns:
        bool: True if all required OIDC environment variables are set.
    """
    return bool(
        os.getenv('OIDC_PROVIDER_URL') and
        os.getenv('OIDC_CLIENT_ID') and
        os.getenv('OIDC_CLIENT_SECRET')
    )


def login_optionally_required(func):
    """
    If authentication is enabled (password or OIDC), verify the user is logged in.
    To be used as a decorator for routes that should optionally require login.
    This version is blueprint-friendly as it uses current_app instead of directly accessing app.
    """
    @wraps(func)
    def decorated_view(*args, **kwargs):
        # Access datastore through the app config
        datastore = current_app.config['DATASTORE']

        # When OIDC is enabled, password auth is ignored - always require auth
        if is_oidc_enabled():
            requires_auth = True
        else:
            requires_auth = (
                datastore.data['settings']['application'].get('password') or
                os.getenv("SALTED_PASS", False)
            )

        # Permitted exceptions
        if (request.endpoint and
            'diff_history_page' in request.endpoint and
            datastore.data['settings']['application'].get('shared_diff_access')):
            return func(*args, **kwargs)
        elif request.method in flask_login.config.EXEMPT_METHODS:
            return func(*args, **kwargs)
        elif current_app.config.get('LOGIN_DISABLED'):
            return func(*args, **kwargs)
        elif requires_auth and not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()

        return func(*args, **kwargs)
    return decorated_view
