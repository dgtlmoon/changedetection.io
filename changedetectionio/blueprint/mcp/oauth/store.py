"""
What OAuth sign-in keeps, without Authlib (so checking a token on every /mcp/v1 call never loads it).

settings.application.mcp_oauth:
  grants:  {grant_id: {name, client_id, client_name, client_host, permissions, tags, resource, access_hash, access_expires,
            refresh_hash, refresh_expires, created, last_used, last_client}}, one per sign-in. The tokens themselves
            are never stored, only their SHA-256, like the access tokens in ../tokens.py.
  clients: {client_id: {client_name, redirect_uris, created, used}}, the ones registered with DCR (/oauth/register).
           CIMD clients aren't stored, their client_id is the URL of their metadata (cimd.py).

Authorization codes live a minute, in memory: the app is one process, and a code is only ever used once, right away.
"""
import hashlib
import hmac
import secrets
import threading
import time

ACCESS_TOKEN_SECONDS = 3600
REFRESH_TOKEN_SECONDS = 30 * 24 * 3600
CODE_SECONDS = 60
# DCR is open to anyone, so registrations are capped, and ones never used for a sign-in are dropped after a day
DCR_MAX_CLIENTS = 200
DCR_UNUSED_SECONDS = 24 * 3600

_codes = {}
_codes_lock = threading.Lock()


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _oauth(app_settings):
    oauth = app_settings.setdefault('mcp_oauth', {})
    oauth.setdefault('grants', {})
    oauth.setdefault('clients', {})
    return oauth


# ---- authorization codes ----

def save_code(code, data):
    now = time.time()
    with _codes_lock:
        for key in [k for k, v in _codes.items() if v['expires'] < now]:
            del _codes[key]
        _codes[_hash(code)] = dict(data, code=code, expires=now + CODE_SECONDS)


def get_code(code):
    with _codes_lock:
        data = _codes.get(_hash(code))
    return data if data and data['expires'] >= time.time() else None


def delete_code(code):
    with _codes_lock:
        _codes.pop(_hash(code), None)


# ---- grants (a signed-in assistant and its tokens) ----

def add_grant(app_settings, *, client_id, client_name, client_host, name, permissions, tags, resource, access_token,
              refresh_token):
    grant_id = secrets.token_hex(8)
    now = int(time.time())
    _oauth(app_settings)['grants'][grant_id] = {
        'name': name, 'client_id': client_id, 'client_name': client_name, 'client_host': client_host,
        'permissions': dict(permissions), 'tags': list(tags or []), 'resource': resource, 'created': now,
        'last_used': None, 'last_client': None,
    }
    rotate(app_settings, grant_id, access_token, refresh_token)
    return grant_id


def rotate(app_settings, grant_id, access_token, refresh_token):
    """New tokens for a grant (on sign-in, and on every refresh: the old refresh token stops working)."""
    grant = _oauth(app_settings)['grants'][grant_id]
    now = int(time.time())
    grant['access_hash'], grant['access_expires'] = _hash(access_token), now + ACCESS_TOKEN_SECONDS
    grant['refresh_hash'], grant['refresh_expires'] = _hash(refresh_token), now + REFRESH_TOKEN_SECONDS


def _find(app_settings, token, kind):
    if not token:
        return None, None
    digest, now = _hash(token), time.time()
    for grant_id, grant in (app_settings.get('mcp_oauth') or {}).get('grants', {}).items():
        if hmac.compare_digest(digest, grant.get(f'{kind}_hash') or '') and (grant.get(f'{kind}_expires') or 0) > now:
            return grant_id, grant
    return None, None


def find_by_access_token(app_settings, token, resource):
    """The grant an access token belongs to, if it's current and was issued for this MCP server (RFC 8707)."""
    _, grant = _find(app_settings, token, 'access')
    return grant if grant and grant.get('resource') == resource else None


def find_by_refresh_token(app_settings, token):
    return _find(app_settings, token, 'refresh')


def grants(app_settings):
    return (app_settings.get('mcp_oauth') or {}).get('grants', {})


def revoke(app_settings, grant_id):
    return _oauth(app_settings)['grants'].pop(grant_id, None) is not None


# ---- clients registered with DCR ----

def register_client(app_settings, client_name, redirect_uris):
    """A new client_id. Prunes first: registrations never used for a sign-in, then the oldest past the cap."""
    clients = _oauth(app_settings)['clients']
    now = int(time.time())
    for client_id in [c for c, v in clients.items() if not v.get('used') and now - v['created'] > DCR_UNUSED_SECONDS]:
        del clients[client_id]
    while len(clients) >= DCR_MAX_CLIENTS:
        del clients[min(clients, key=lambda c: (bool(clients[c].get('used')), clients[c]['created']))]
    client_id = 'cdio-' + secrets.token_urlsafe(16)
    clients[client_id] = {'client_name': client_name, 'redirect_uris': list(redirect_uris), 'created': now, 'used': None}
    return client_id


def get_client(app_settings, client_id):
    return (app_settings.get('mcp_oauth') or {}).get('clients', {}).get(client_id)


def mark_client_used(app_settings, client_id):
    client = get_client(app_settings, client_id)
    if client is not None:
        client['used'] = int(time.time())
