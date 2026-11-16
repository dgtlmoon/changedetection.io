"""
OAuth 2.1 sign-in for the MCP server, so assistants that only connect with sign-in (claude.ai, ChatGPT in the browser)
can use /mcp/v1. Design and research: MCP-config.md, "3. OAuth 2.1".

Every instance is its own authorization server and its own MCP resource ("core stands alone"): the user pastes their
own /mcp/v1 address as a custom connector, the assistant discovers the sign-in from the 401 /mcp/v1 answers, the user
logs in with the instance's password and picks what the assistant may do, and the assistant gets tokens for /mcp/v1.

Offered only while the MCP switch is on (settings.application.mcp_enabled) and a password is set, sign-in needs a
login to sit behind. Otherwise every route here is a 404, before anything else is done with the request.

Nothing heavy loads until it's used: this module only registers the routes. The discovery documents below are plain
JSON, and Authlib is imported only by the authorize and token endpoints, so the instances that never use OAuth (most
of them) don't pay for it. test_oauth_imported_lazily guards that.
"""
import os
import threading
import time
from urllib.parse import urlsplit

from flask import Blueprint, abort, g, jsonify, render_template, request

# Signing algorithms accepted for private_key_jwt: asymmetric only, the key is the client's public one
ASSERTION_ALGORITHMS = ['RS256', 'RS384', 'RS512', 'PS256', 'PS384', 'PS512', 'ES256', 'ES384', 'ES512', 'EdDSA']

# The scope every token gets; what it may do is the token's None / Read / Write grid, picked on the consent screen
SCOPE = 'mcp'

# DCR (/oauth/register) is open to anyone: a small body, and a few registrations per address per hour
REGISTER_MAX_BYTES = 5 * 1024
REGISTER_PER_HOUR = 10
_register_log = {}
_register_lock = threading.Lock()


def password_set(datastore):
    return bool(datastore.data['settings']['application'].get('password') or os.getenv('SALTED_PASS', False))


def oauth_available(datastore):
    """Sign-in is offered: MCP is on (and not switched off for good) and there is a login to sit behind."""
    from changedetectionio.blueprint.mcp import is_mcp_disabled
    return (not is_mcp_disabled() and bool(datastore.data['settings']['application'].get('mcp_enabled'))
            and password_set(datastore))


def issuer(datastore):
    """This instance's public address for MCP, the issuer of its tokens: the "Public MCP address" setting
    (settings.application.mcp_base_url, MCP Server > Settings) when set, otherwise built from the request,
    X-Forwarded-Prefix/Host/Proto included. Separate from the notification Base URL on purpose: changing it signs out
    every OAuth connection, since grants are bound to {issuer}/mcp/v1."""
    base = (datastore.data['settings']['application'].get('mcp_base_url') or '').strip()
    return (base or request.url_root).rstrip('/')


def secure_issuer(datastore):
    """Sign-in only over https (OAuth 2.1), checked on the address clients use, not on what Flask sees: behind a
    proxy that ends TLS, Flask sees http. Plain http only for localhost (developing, testing)."""
    parts = urlsplit(issuer(datastore))
    return parts.scheme == 'https' or parts.hostname in ('localhost', '127.0.0.1', '::1')


def resource(datastore):
    """The MCP server's address, the audience tokens are issued for (RFC 8707)."""
    return issuer(datastore) + '/mcp/v1'


def resource_metadata_url(datastore):
    """Where the 401 from /mcp/v1 points clients (RFC 9728, the path-specific form they try first)."""
    return issuer(datastore) + '/.well-known/oauth-protected-resource/mcp/v1'


def construct_blueprint(datastore):
    oauth_blueprint = Blueprint('mcp_oauth', __name__, template_folder='templates')

    @oauth_blueprint.before_request
    def only_when_offered():
        if not oauth_available(datastore):
            abort(404)

    @oauth_blueprint.route('/.well-known/oauth-protected-resource', methods=['GET'])
    @oauth_blueprint.route('/.well-known/oauth-protected-resource/mcp/v1', methods=['GET'])
    def protected_resource_metadata():
        # RFC 9728: which authorization server issues tokens for /mcp/v1
        return jsonify({
            'resource': resource(datastore),
            'authorization_servers': [issuer(datastore)],
            'bearer_methods_supported': ['header'],
            'scopes_supported': [SCOPE],
            'resource_name': 'changedetection.io',
        })

    @oauth_blueprint.route('/.well-known/oauth-authorization-server', methods=['GET'])
    # The same document where clients look when the issuer has a path (behind a proxy at /some-prefix, like every
    # hosted instance): RFC 8414's place for that is at the host root, /.well-known/oauth-authorization-server/
    # some-prefix, which never reaches this instance. Clients then try {issuer}/.well-known/openid-configuration, which
    # does (MCP spec, authorization server discovery). No openid scope is offered, so it's no OpenID provider
    @oauth_blueprint.route('/.well-known/openid-configuration', methods=['GET'])
    def authorization_server_metadata():
        # RFC 8414. No client secrets (CIMD forbids them): public clients, or clients signing with their own key
        # (private_key_jwt, CIMD only). Authorization code with PKCE S256, refresh tokens
        base = issuer(datastore)
        return jsonify({
            'issuer': base,
            'authorization_endpoint': base + '/oauth/authorize',
            'token_endpoint': base + '/oauth/token',
            'registration_endpoint': base + '/oauth/register',
            'scopes_supported': [SCOPE],
            'response_types_supported': ['code'],
            'grant_types_supported': ['authorization_code', 'refresh_token'],
            'code_challenge_methods_supported': ['S256'],
            'token_endpoint_auth_methods_supported': ['none', 'private_key_jwt'],
            'token_endpoint_auth_signing_alg_values_supported': ASSERTION_ALGORITHMS,
            # A client_id can be an https URL to the client's own metadata (CIMD), no registration needed
            'client_id_metadata_document_supported': True,
            # RFC 9207, ChatGPT needs it for its stable redirect URI
            'authorization_response_iss_parameter_supported': True,
        })

    def consent_page(error=None, status=200, **context):
        return render_template('mcp-oauth-consent.html', error=error, **context), status

    def with_issuer(response):
        """RFC 9207: the authorization response (errors included) says who issued it."""
        from authlib.common.urls import add_params_to_uri
        location = response.headers.get('Location')
        if response.status_code in (301, 302, 303) and location:
            response.headers['Location'] = add_params_to_uri(location, [('iss', issuer(datastore))])
        return response

    @oauth_blueprint.route('/oauth/authorize', methods=['GET', 'POST'])
    def authorize():
        """The consent screen. Behind the instance's login (the login gate in flask_app.py sends a logged-out user to
        /login and back here). GET shows it, POST is the answer, with the CSRF token like any other form."""
        from authlib.oauth2 import OAuth2Error
        # The same name, None / Read / Write grid and groups as an access token
        from changedetectionio.blueprint.settings.llm import mcp_token_form
        from . import server as oauth_server

        if not secure_issuer(datastore):
            return consent_page(error="Sign-in needs https. Set the Public MCP address (AI > MCP Server > Settings) to "
                                      "this instance's https address.", status=400)
        # Authlib's PKCE accepts no challenge, or "plain": MCP requires S256
        if request.args.get('code_challenge_method') != 'S256' or not request.args.get('code_challenge'):
            return consent_page(error="This sign-in needs PKCE with code_challenge_method=S256.", status=400)
        requested = (request.args.get('resource') or '').rstrip('/')
        if requested and requested != resource(datastore):
            return consent_page(error=f"This sign-in is only for {resource(datastore)}, not {requested}.", status=400)
        g.mcp_oauth_resource = resource(datastore)

        auth_server = oauth_server.get_server()
        try:
            grant = auth_server.get_consent_grant(end_user=oauth_server.OWNER)
        except OAuth2Error as e:
            # Before the redirect URI is known to be the client's, errors are shown here, never redirected
            detail = g.get('mcp_oauth_client_error') or e.description or e.error
            return consent_page(error=f"The assistant's sign-in request can't be used: {detail}", status=400)

        client = grant.request.client
        redirect_uri = grant.request.payload.redirect_uri or client.get_default_redirect_uri()
        redirect_host = urlsplit(redirect_uri or '').hostname or ''
        if request.method == 'POST':
            if request.form.get('decision') != 'approve':
                return with_issuer(auth_server.create_authorization_response(grant_user=None, grant=grant))
            form = mcp_token_form(datastore, request.form)
            if form.validate():
                from changedetectionio.blueprint.mcp.tools import permission_defaults
                g.mcp_oauth_consent = {'name': form.name.data.strip(),
                                       'permissions': {a: form[f'perm_{a}'].data for a in permission_defaults()},
                                       'tags': list(form.tags.data or [])}
                return with_issuer(auth_server.create_authorization_response(grant_user=oauth_server.OWNER,
                                                                             grant=grant))
        else:
            form = mcp_token_form(datastore)
            form.name.data = client.client_name
        return consent_page(form=form, client=client, redirect_host=redirect_host,
                            localhost_only=redirect_host in ('localhost', '127.0.0.1', '::1'),
                            mcp_url=resource(datastore))

    @oauth_blueprint.route('/oauth/token', methods=['POST'])
    def token():
        """Code (with the PKCE verifier) or refresh token in, tokens out. Called by the assistant's server."""
        if not secure_issuer(datastore):
            return jsonify({'error': 'invalid_request', 'error_description': 'Sign-in needs https'}), 400
        requested = (request.form.get('resource') or '').rstrip('/')
        if requested and requested != resource(datastore):
            return jsonify({'error': 'invalid_target', 'error_description': f"Tokens here are only for {resource(datastore)}"}), 400
        from . import server as oauth_server
        return oauth_server.get_server().create_token_response()

    @oauth_blueprint.route('/oauth/register', methods=['POST'])
    def register():
        """DCR (RFC 7591), for clients that don't do CIMD yet. Open to anyone, so: small, rate limited, public clients
        only, and the name it gives is shown as unverified on the consent screen. A client asking for another
        token_endpoint_auth_method gets 'none' in the answer (RFC 7591 3.2.1): signing with a key from a jwks_uri anyone
        could register would make this server fetch from wherever it's told."""
        from . import store

        def refuse(error, description, status=400):
            return jsonify({'error': error, 'error_description': description}), status

        if (request.content_length or 0) > REGISTER_MAX_BYTES:
            return refuse('invalid_client_metadata', 'Too large', 413)
        now, address = time.time(), request.remote_addr or ''
        with _register_lock:
            recent = [t for t in _register_log.get(address, []) if now - t < 3600]
            if len(recent) >= REGISTER_PER_HOUR:
                return refuse('invalid_client_metadata', 'Too many registrations, try again later', 429)
            _register_log[address] = recent + [now]

        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return refuse('invalid_client_metadata', 'Expected a JSON object')
        redirect_uris = body.get('redirect_uris')
        if not isinstance(redirect_uris, list) or not 0 < len(redirect_uris) <= 10:
            return refuse('invalid_redirect_uri', 'redirect_uris must list 1 to 10 URIs')
        for uri in redirect_uris:
            parts = urlsplit(uri) if isinstance(uri, str) else None
            loopback = parts is not None and parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')
            if not parts or parts.fragment or not (parts.scheme == 'https' and parts.hostname or loopback):
                return refuse('invalid_redirect_uri', f'{uri!r} must be an https URI, or http on localhost')
        if not set(body.get('grant_types') or ['authorization_code']) <= {'authorization_code', 'refresh_token'}:
            return refuse('invalid_client_metadata', 'Only the authorization_code and refresh_token grant types')
        name = body.get('client_name')
        name = name.strip()[:100] if isinstance(name, str) and name.strip() else 'Unnamed assistant'

        app_settings = datastore.data['settings']['application']
        client_id = store.register_client(app_settings, name, redirect_uris)
        datastore.commit()
        return jsonify({'client_id': client_id, 'client_id_issued_at': int(now), 'client_name': name,
                        'redirect_uris': redirect_uris, 'token_endpoint_auth_method': 'none',
                        'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code']}), 201

    return oauth_blueprint
