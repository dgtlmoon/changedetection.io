"""
Named MCP access tokens, one per assistant, each with its own None / Read / Write permissions (see tools.permissions()).

Stored in settings.application.mcp_tokens as {token_id: {name, hint, hash, permissions, tags, created, last_used,
last_client}}. tags: the uuids of the tags (groups) the token is limited to, empty for every monitor (tools.Context). Only a SHA-256 of each token is kept: the token itself is shown once, when it's created (like GitHub
personal access tokens), so reading the datastore doesn't give anyone access. `hint` is its first characters, so the
list can show which token is which. Managed on the "Access tokens" sub-tab of /settings/ai/mcp.
"""
import hashlib
import hmac
import secrets
import time

PREFIX = 'cdio_mcp_'
# "Last used" is saved at most this often per token, not on every request
LAST_USED_EVERY = 300
NAME_MAX = 64


def _hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


def add_token(app_settings, name, permissions, tags=None):
    """(token_id, the token itself), the only time the token is available."""
    token = PREFIX + secrets.token_hex(20)
    token_id = secrets.token_hex(8)
    app_settings.setdefault('mcp_tokens', {})[token_id] = {
        'name': name[:NAME_MAX], 'hint': token[:len(PREFIX) + 4], 'hash': _hash(token),
        'permissions': dict(permissions), 'tags': list(tags or []), 'created': int(time.time()), 'last_used': None,
        'last_client': None,
    }
    return token_id, token


def find_token(app_settings, given):
    """The stored token matching what a client sent, or None."""
    if not given:
        return None
    digest = _hash(given)
    for token in (app_settings.get('mcp_tokens') or {}).values():
        if hmac.compare_digest(digest, token.get('hash') or ''):
            return token
    return None


def mark_used(token, client=None):
    """Note that the token was used (and by which client, from `initialize`). True when that's worth saving now."""
    now = int(time.time())
    changed = bool(client) and client != token.get('last_client')
    if changed:
        token['last_client'] = client[:NAME_MAX]
    if changed or now - (token.get('last_used') or 0) >= LAST_USED_EVERY:
        token['last_used'] = now
        return True
    return False
