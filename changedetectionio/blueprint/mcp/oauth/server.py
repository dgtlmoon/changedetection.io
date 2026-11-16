"""
The OAuth authorization server, on Authlib. Imported only by the authorize and token endpoints (see __init__.py),
never at startup.

No client secrets (CIMD forbids them, and DCR clients here get none). A client is public (token_endpoint_auth_method
'none', PKCE alone) or, from CIMD only, signs every token request with its own key (private_key_jwt, RFC 7523, like
ChatGPT): whichever its metadata says, and only that one. The authorization code grant with PKCE S256 required either
way, and refresh tokens that rotate on every use (OAuth 2.1). Tokens are random strings, stored hashed
(store.py) and bound to this instance's /mcp/v1 (resource / audience). What a token may do is the None / Read / Write
grid picked on the consent screen, carried on the authorization code into the grant.
"""
import threading
import time
from urllib.parse import urlsplit

from authlib.integrations.flask_oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749 import AuthorizationCodeMixin, ClientMixin, InvalidClientError, TokenMixin, grants
from authlib.oauth2.rfc7523 import JWTBearerClientAssertion
from authlib.oauth2.rfc7636 import CodeChallenge
from flask import current_app, g

from . import ASSERTION_ALGORITHMS, SCOPE, cimd, issuer, store

# There is one user, the instance's owner (its password)
OWNER = 'owner'

LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')


def redirect_uri_matches(registered, given):
    """Exact match, except that an http redirect URI on this computer (loopback) matches on any port, RFC 8252 7.3.
    Apps on the user's computer (Claude Code, Cursor...) listen on a port picked at sign-in time, so their metadata
    lists http://localhost/callback and the request names http://localhost:53228/callback."""
    if given == registered:
        return True
    reg, req = urlsplit(registered), urlsplit(given)
    if reg.scheme != 'http' or req.scheme != 'http' or reg.hostname not in LOOPBACK_HOSTS:
        return False
    try:
        _ = req.port  # an invalid port raises ValueError
    except ValueError:
        return False
    return (req.hostname == reg.hostname and req.path == reg.path and req.query == reg.query
            and not req.fragment and req.username is None and req.password is None)


class Client(ClientMixin):
    def __init__(self, client_id, client_name, redirect_uris, kind, auth_method='none', jwks_uri=None):
        self.client_id, self.client_name, self.redirect_uris, self.kind = client_id, client_name, redirect_uris, kind
        self.auth_method, self.jwks_uri = auth_method, jwks_uri

    @property
    def host(self):
        """For the consent screen: a CIMD client's URL host is real, a DCR client's name is only what it said."""
        return urlsplit(self.client_id).hostname if self.kind == 'cimd' else None

    def get_client_id(self):
        return self.client_id

    def get_default_redirect_uri(self):
        return self.redirect_uris[0] if len(self.redirect_uris) == 1 else None

    def get_allowed_scope(self, scope):
        return SCOPE

    def check_redirect_uri(self, redirect_uri):
        # Exact match, any port on loopback (redirect_uri_matches)
        return any(redirect_uri_matches(registered, redirect_uri) for registered in self.redirect_uris)

    def check_client_secret(self, client_secret):
        return False

    def check_endpoint_auth_method(self, method, endpoint):
        # Only the method its metadata names: a signing client sending no signature is refused
        return method == self.auth_method

    def check_response_type(self, response_type):
        return response_type == 'code'

    def check_grant_type(self, grant_type):
        return grant_type in ('authorization_code', 'refresh_token')


class AuthorizationCode(AuthorizationCodeMixin):
    def __init__(self, data):
        self.data = data
        self.code = data['code']
        self.code_challenge = data['code_challenge']
        self.code_challenge_method = data['code_challenge_method']

    def get_redirect_uri(self):
        return self.data['redirect_uri']

    def get_scope(self):
        return SCOPE


class RefreshCredential(TokenMixin):
    def __init__(self, grant_id, grant):
        self.grant_id, self.grant = grant_id, grant

    def check_client(self, client):
        return client.get_client_id() == self.grant['client_id']

    def get_scope(self):
        return SCOPE

    def get_expires_in(self):
        return store.REFRESH_TOKEN_SECONDS

    def is_expired(self):
        return False  # find_by_refresh_token only returns current ones

    def is_revoked(self):
        return False


# Assertions are short-lived; one that claims to be valid for longer than this is refused, so the replay list stays small
ASSERTION_MAX_SECONDS = 3600


class PrivateKeyJWT(JWTBearerClientAssertion):
    """private_key_jwt (RFC 7523 section 2.2, OIDC Core 9): the client signs a short JWT with its own key, checked
    against the key set at its jwks_uri. Authlib checks the signature, iss = sub = client_id, aud and exp; this adds
    where the keys come from, the algorithms, and that each assertion (jti) is used once."""
    CLIENT_AUTH_METHOD = 'private_key_jwt'

    _seen = {}
    _seen_lock = threading.Lock()

    def get_audiences(self):
        # This server, or its token endpoint (both are common), at its public address
        base = issuer(current_app.config['DATASTORE'])
        return [base, base + '/oauth/token']

    def resolve_client_public_key(self, client):
        from flask import request
        if client.auth_method != 'private_key_jwt' or not client.jwks_uri:
            raise InvalidClientError(description="This client doesn't sign its requests")
        # The assertion names the client (sub); a client_id sent alongside it must be the same one
        if request.form.get('client_id') not in (None, client.get_client_id()):
            raise InvalidClientError(description="client_id doesn't match the client assertion")

        def key_for(token):
            from joserfc.errors import JoseError
            from joserfc.jwk import KeySet
            kid = token.headers().get('kid')
            try:
                for refresh in (False, True):
                    keys = KeySet.import_key_set(cimd.fetch_jwks(client.jwks_uri, refresh=refresh))
                    try:
                        return keys.get_by_kid(kid)
                    except JoseError:
                        if kid is None:
                            break  # no kid and more than one key: which one is unknowable
            except (cimd.CIMDError, JoseError, ValueError) as e:
                raise InvalidClientError(description=f"The client's keys can't be used: {e}")
            raise InvalidClientError(description="No key in the client's key set matches the assertion")
        return key_for

    def process_assertion_claims(self, assertion, resolve_key):
        from joserfc import jwt
        from joserfc.errors import JoseError
        try:
            token = jwt.decode(assertion, resolve_key, algorithms=ASSERTION_ALGORITHMS)
        except JoseError as e:
            raise InvalidClientError(description=e.description or 'Invalid client assertion')
        self.verify_claims(token.claims)
        return token.claims

    def validate_jti(self, claims, jti):
        now = time.time()
        exp = claims.get('exp')
        if not isinstance(exp, (int, float)) or exp - now > ASSERTION_MAX_SECONDS:
            return False
        key = (claims['iss'], str(jti))
        with self._seen_lock:
            for k in [k for k, until in self._seen.items() if until < now]:
                del self._seen[k]
            if key in self._seen:
                return False
            # Kept past exp by the leeway Authlib allows on it
            self._seen[key] = exp + self.leeway
        return True


# Signing clients first: a request without an assertion falls through to 'none', which a signing client fails
TOKEN_AUTH_METHODS = ['private_key_jwt', 'none']


class CodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = TOKEN_AUTH_METHODS

    def save_authorization_code(self, code, request):
        data = request.payload.data
        store.save_code(code, {
            'client_id': request.client.get_client_id(), 'redirect_uri': data.get('redirect_uri'),
            'code_challenge': data.get('code_challenge'), 'code_challenge_method': data.get('code_challenge_method'),
            # Checked by the authorize view (this MCP server's address, also when the client didn't send one)
            'resource': g.mcp_oauth_resource,
            # The consent screen's answer: the name for the token list and the None / Read / Write grid
            'consent': g.mcp_oauth_consent,
        })

    def query_authorization_code(self, code, client):
        data = store.get_code(code)
        return AuthorizationCode(data) if data and data['client_id'] == client.get_client_id() else None

    def delete_authorization_code(self, authorization_code):
        store.delete_code(authorization_code.code)

    def authenticate_user(self, authorization_code):
        return OWNER


class RefreshGrant(grants.RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = TOKEN_AUTH_METHODS
    # OAuth 2.1: a public client's refresh token is replaced on every use
    INCLUDE_NEW_REFRESH_TOKEN = True

    def authenticate_refresh_token(self, refresh_token):
        grant_id, grant = store.find_by_refresh_token(current_app.config['DATASTORE'].data['settings']['application'],
                                                      refresh_token)
        return RefreshCredential(grant_id, grant) if grant else None

    def authenticate_user(self, credential):
        return OWNER

    def revoke_old_credential(self, credential):
        pass  # save_token already replaced it


def query_client(client_id):
    """A client by client_id: a CIMD URL (fetched, cached briefly) or one registered with DCR."""
    if cimd.is_client_id_url(client_id):
        try:
            doc = cimd.fetch(client_id)
        except cimd.CIMDError as e:
            g.mcp_oauth_client_error = str(e)
            return None
        return Client(client_id, doc['client_name'], doc['redirect_uris'], 'cimd',
                      auth_method=doc['auth_method'], jwks_uri=doc.get('jwks_uri'))
    registered = store.get_client(current_app.config['DATASTORE'].data['settings']['application'], client_id or '')
    if registered:
        return Client(client_id, registered['client_name'], registered['redirect_uris'], 'dcr')
    return None


def save_token(token, request):
    datastore = current_app.config['DATASTORE']
    app_settings = datastore.data['settings']['application']
    if request.payload.grant_type == 'authorization_code':
        code, client = request.authorization_code, request.client
        consent = code.data['consent']
        store.add_grant(app_settings, client_id=client.get_client_id(), client_name=client.client_name,
                        client_host=client.host, name=consent['name'], permissions=consent['permissions'],
                        tags=consent.get('tags'),
                        resource=code.data['resource'], access_token=token['access_token'],
                        refresh_token=token['refresh_token'])
        store.mark_client_used(app_settings, client.get_client_id())
    else:
        store.rotate(app_settings, request.refresh_token.grant_id, token['access_token'], token['refresh_token'])
    datastore.commit()


def get_server():
    """The authorization server for this app, made on first use."""
    app = current_app._get_current_object()
    server = app.extensions.get('mcp_oauth_server')
    if server is None:
        # Authlib checks https on the URL Flask sees, which is http behind a proxy that ends TLS. The views check it
        # on the address clients use instead (secure_issuer()), so Authlib's own check is switched off
        import os
        os.environ['AUTHLIB_INSECURE_TRANSPORT'] = '1'
        app.config.setdefault('OAUTH2_REFRESH_TOKEN_GENERATOR', True)
        app.config.setdefault('OAUTH2_TOKEN_EXPIRES_IN', {'authorization_code': store.ACCESS_TOKEN_SECONDS,
                                                          'refresh_token': store.ACCESS_TOKEN_SECONDS})
        server = AuthorizationServer()
        server.init_app(app, query_client=query_client, save_token=save_token)
        server.register_client_auth_method(PrivateKeyJWT.CLIENT_AUTH_METHOD, PrivateKeyJWT())
        server.register_grant(CodeGrant, [CodeChallenge(required=True)])
        server.register_grant(RefreshGrant)
        app.extensions['mcp_oauth_server'] = server
    return server
