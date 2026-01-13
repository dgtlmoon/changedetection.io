"""
OIDC Authentication Blueprint for changedetection.io

Provides OpenID Connect authentication with:
- Environment-variable-only configuration
- Group-based access control via OIDC groups claim
- Integration with existing flask_login User model

Environment Variables:
    OIDC_PROVIDER_URL: Discovery URL (e.g., https://kanidm.example.com/oauth2/openid/changedetection)
    OIDC_CLIENT_ID: OAuth2 client ID
    OIDC_CLIENT_SECRET: OAuth2 client secret
    OIDC_ALLOWED_GROUPS: Comma-separated list of allowed groups (required, empty = deny all)
    OIDC_GROUPS_CLAIM: Claim name containing groups (default: "groups")
    OIDC_SCOPES: Space or comma-separated scopes (default: "openid email profile groups_name")
"""

import os

import flask_login
from flask import Blueprint, flash, redirect, request, session, url_for
from flask_babel import gettext
from loguru import logger


def get_oidc_config():
    """
    Load OIDC configuration from environment variables.

    Returns:
        dict: Configuration dictionary, or None if OIDC is not configured.
    """
    provider_url = os.getenv('OIDC_PROVIDER_URL')
    if not provider_url:
        return None

    # Handle scopes - can be comma or space separated
    scopes_raw = os.getenv('OIDC_SCOPES', 'openid email profile groups_name')
    scopes = scopes_raw.replace(',', ' ')

    # Parse allowed groups - comma separated
    allowed_groups_raw = os.getenv('OIDC_ALLOWED_GROUPS', '')
    allowed_groups = [g.strip() for g in allowed_groups_raw.split(',') if g.strip()]

    return {
        'provider_url': provider_url.rstrip('/'),
        'client_id': os.getenv('OIDC_CLIENT_ID'),
        'client_secret': os.getenv('OIDC_CLIENT_SECRET'),
        'allowed_groups': allowed_groups,
        'groups_claim': os.getenv('OIDC_GROUPS_CLAIM', 'groups'),
        'scopes': scopes,
    }


def is_oidc_enabled():
    """
    Check if OIDC authentication is configured and enabled.

    Returns:
        bool: True if all required OIDC environment variables are set.
    """
    return bool(
        os.getenv('OIDC_PROVIDER_URL') and
        os.getenv('OIDC_CLIENT_ID') and
        os.getenv('OIDC_CLIENT_SECRET')
    )


def construct_blueprint(datastore):  # noqa: C901
    """
    Construct the OIDC authentication blueprint.

    Args:
        datastore: The ChangeDetectionStore instance (for consistency with other blueprints).

    Returns:
        tuple: (blueprint, oauth) - The Flask blueprint and OAuth instance.
    """
    oidc_blueprint = Blueprint('oidc', __name__)

    # Initialize OAuth only if OIDC is configured
    oauth = None
    oidc_client = None

    config = get_oidc_config()
    if config and config.get('client_id') and config.get('client_secret'):
        from authlib.integrations.flask_client import OAuth
        oauth = OAuth()

        # Build the discovery URL
        # Kanidm uses: {provider_url}/.well-known/openid-configuration
        discovery_url = config['provider_url']
        if not discovery_url.endswith('/.well-known/openid-configuration'):
            discovery_url = discovery_url + '/.well-known/openid-configuration'

        # Configure OIDC client with discovery
        oidc_client = oauth.register(
            name='oidc',
            client_id=config['client_id'],
            client_secret=config['client_secret'],
            server_metadata_url=discovery_url,
            client_kwargs={
                'scope': config['scopes'],
            }
        )
        logger.info(f"OIDC client registered with provider: {config['provider_url']}")

    @oidc_blueprint.route('/login')
    def login():
        """Initiate OIDC login flow."""
        if not oidc_client:
            logger.error("OIDC login attempted but client not configured")
            flash(gettext('OIDC authentication is not configured'), 'error')
            return redirect(url_for('watchlist.index'))

        # Store redirect target in session
        redirect_after = request.args.get('redirect', url_for('watchlist.index'))
        session['oidc_redirect_after'] = redirect_after

        # Build the callback URL
        redirect_uri = url_for('oidc.callback', _external=True)
        logger.debug(f"OIDC login initiated, callback URL: {redirect_uri}")

        return oidc_client.authorize_redirect(redirect_uri)

    @oidc_blueprint.route('/callback')
    def callback():
        """Handle OIDC callback after authentication at the provider."""
        if not oidc_client:
            logger.error("OIDC callback received but client not configured")
            flash(gettext('OIDC authentication is not configured'), 'error')
            return redirect(url_for('watchlist.index'))

        # Exchange authorization code for tokens
        try:
            token = oidc_client.authorize_access_token()
        except Exception as e:
            logger.error(f"OIDC token exchange failed: {e}")
            flash(gettext('Authentication failed - could not obtain token'), 'error')
            return redirect(url_for('login'))

        # Get user info - try from token first, then userinfo endpoint
        try:
            userinfo = token.get('userinfo')
            if not userinfo:
                userinfo = oidc_client.userinfo(token=token)
        except Exception as e:
            logger.error(f"OIDC userinfo fetch failed: {e}")
            flash(gettext('Authentication failed - could not fetch user info'), 'error')
            return redirect(url_for('login'))

        logger.debug(f"OIDC userinfo received: {userinfo}")

        # Check group membership
        config = get_oidc_config()
        allowed_groups = config.get('allowed_groups', [])
        groups_claim = config.get('groups_claim', 'groups')

        # Extract groups from userinfo
        user_groups = userinfo.get(groups_claim, [])
        if isinstance(user_groups, str):
            user_groups = [user_groups]

        user_email = userinfo.get('email', userinfo.get('sub', 'unknown'))

        # Fail-closed: deny access if no allowed groups configured
        if not allowed_groups:
            logger.warning(
                f"OIDC login denied for {user_email} - OIDC_ALLOWED_GROUPS is empty (fail-closed)"
            )
            flash(gettext('Access denied - no allowed groups configured'), 'error')
            return redirect(url_for('login'))

        # Check if user is in any allowed group
        matching_groups = [g for g in user_groups if g in allowed_groups]
        if not matching_groups:
            logger.warning(
                f"OIDC login denied for {user_email} - not in allowed groups. "
                f"User groups: {user_groups}, Allowed: {allowed_groups}"
            )
            flash(gettext('Access denied - you are not in an authorized group'), 'error')
            return redirect(url_for('login'))

        logger.info(f"OIDC login authorized for {user_email} via groups: {matching_groups}")

        # Create and login user
        # Import here to avoid circular imports
        from changedetectionio.flask_app import User
        user = User()
        user.id = user_email
        user.oidc_authenticated = True

        # Store user info in session for potential use
        session['oidc_userinfo'] = {
            'email': userinfo.get('email'),
            'name': userinfo.get('name'),
            'sub': userinfo.get('sub'),
            'groups': user_groups,
        }

        flask_login.login_user(user, remember=True)
        logger.info(f"OIDC login successful for {user.id}")

        # Redirect to original destination
        redirect_target = session.pop('oidc_redirect_after', url_for('watchlist.index'))
        return redirect(redirect_target)

    @oidc_blueprint.route('/logout')
    def logout():
        """Handle OIDC logout (local session only)."""
        user_email = session.get('oidc_userinfo', {}).get('email', 'unknown')

        # Clear OIDC session data
        session.pop('oidc_userinfo', None)
        session.pop('oidc_redirect_after', None)

        # Logout from flask_login
        flask_login.logout_user()

        logger.info(f"OIDC logout for {user_email}")
        flash(gettext('Logged out successfully'))

        return redirect(url_for('watchlist.index'))

    return oidc_blueprint, oauth
