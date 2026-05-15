import os
from functools import wraps
from flask import current_app, redirect, request
from loguru import logger

# Endpoints exempt from auth when `shared_diff_access` is enabled.
# Must be exact endpoint names — substring matching (GHSA-vwgh-2hvh-4xm5)
# let the state-changing `/diff/<uuid>/extract` endpoints slip through
# because their names share the `diff_history_page` prefix.
SHARED_DIFF_READ_ONLY_ENDPOINTS = frozenset({
    'ui.ui_diff.diff_history_page',
    'ui.ui_diff.processor_asset',
    'ui.ui_diff.download_patch',
})

def login_optionally_required(func):
    """
    If password authentication is enabled, verify the user is logged in.
    To be used as a decorator for routes that should optionally require login.
    This version is blueprint-friendly as it uses current_app instead of directly accessing app.
    """
    @wraps(func)
    def decorated_view(*args, **kwargs):
        from flask import current_app
        import flask_login
        from flask_login import current_user

        # Access datastore through the app config
        datastore = current_app.config['DATASTORE']
        has_password_enabled = datastore.data['settings']['application'].get('password') or os.getenv("SALTED_PASS", False)

        # Permitted
        if request.endpoint in SHARED_DIFF_READ_ONLY_ENDPOINTS and datastore.data['settings']['application'].get('shared_diff_access'):
            return func(*args, **kwargs)
        elif request.method in flask_login.config.EXEMPT_METHODS:
            return func(*args, **kwargs)
        elif current_app.config.get('LOGIN_DISABLED'):
            return func(*args, **kwargs)
        elif has_password_enabled and not current_user.is_authenticated:
            return current_app.login_manager.unauthorized()

        return func(*args, **kwargs)
    return decorated_view