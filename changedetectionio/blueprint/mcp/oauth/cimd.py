"""
CIMD (OAuth Client ID Metadata Documents, draft-ietf-oauth-client-id-metadata-document-02): a client_id that is an
https URL, fetching it gives the client's metadata (name, redirect URIs). No registration, the URL is the client.

The fetch goes to a URL the client chose, so it's made safe against SSRF the way the draft requires: every address the
host resolves to must be a public one, and the connection is made to that checked address (the TLS certificate is
still verified for the hostname), so a second DNS answer can't point it somewhere else. No redirects, at most 5 KB,
only a 200 counts, a short timeout. ALLOW_IANA_RESTRICTED_ADDRESSES doesn't apply here: the draft allows no exception.

A client that signs its token requests (private_key_jwt, RFC 7523, like ChatGPT) names its public keys with jwks_uri.
That has to be on the client_id's own host, and is fetched the same safe way (fetch_jwks).

No Authlib, only urllib3 (already here through requests).
"""
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlsplit

MAX_BYTES = 5 * 1024
# A few RSA keys while one is being rotated out
JWKS_MAX_BYTES = 20 * 1024
TIMEOUT_SECONDS = 5
# Documents are cached briefly; errors never are
CACHE_SECONDS = 300
# A key that isn't in the cached key set refetches it (the client rotated its keys), at most this often
JWKS_REFETCH_SECONDS = 30

# How a client may authenticate at the token endpoint: public (PKCE only), or signing a JWT with its own key
AUTH_METHODS = ('none', 'private_key_jwt')

_cache = {}
_cache_lock = threading.Lock()
_jwks_cache = {}


class CIMDError(Exception):
    """Why a client_id URL can't be used, readable on the sign-in page."""


def is_client_id_url(client_id):
    return isinstance(client_id, str) and client_id.startswith('https://')


def validate_client_id_url(url):
    """The draft's rules for the URL itself: https, a path that isn't just '/', no user info, no fragment, no '.' or
    '..' segments (no query is a should, not checked)."""
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname:
        raise CIMDError("the client_id must be an https URL")
    if parts.username or parts.password or '@' in parts.netloc:
        raise CIMDError("the client_id URL can't contain a user name or password")
    if parts.fragment or '#' in url:
        raise CIMDError("the client_id URL can't have a fragment")
    if not parts.path or parts.path == '/':
        raise CIMDError("the client_id URL must have a path")
    if any(segment in ('.', '..') for segment in parts.path.split('/')):
        raise CIMDError("the client_id URL can't contain '.' or '..' path segments")
    return parts


def is_public_address(address):
    """Not loopback, private, link-local, multicast, reserved or otherwise special-use (RFC 6890)."""
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def _public_address_for(hostname, port):
    try:
        infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise CIMDError(f"{hostname} can't be resolved")
    addresses = {info[4][0] for info in infos}
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise CIMDError(f"{hostname} isn't a public address")
    return sorted(addresses)[0]


def _fetch_document(url):
    """The raw metadata document at url. Separate from fetch() so tests can stand in."""
    return _fetch(url, MAX_BYTES, "the client's metadata")


def _fetch_jwks(url):
    """The raw key set at a client's jwks_uri. Separate from fetch_jwks() so tests can stand in."""
    return _fetch(url, JWKS_MAX_BYTES, "the client's keys")


def _fetch(url, max_bytes, what):
    """The raw body at url, fetched from a checked public address."""
    import urllib3
    parts = validate_client_id_url(url)
    port = parts.port or 443
    address = _public_address_for(parts.hostname, port)
    pool = urllib3.HTTPSConnectionPool(address, port=port, server_hostname=parts.hostname,
                                       assert_hostname=parts.hostname, timeout=TIMEOUT_SECONDS, retries=False,
                                       cert_reqs='CERT_REQUIRED')
    path = parts.path + (f'?{parts.query}' if parts.query else '')
    try:
        response = pool.urlopen('GET', path, headers={'Host': parts.netloc, 'Accept': 'application/json'},
                                redirect=False, preload_content=False)
        if response.status != 200:
            raise CIMDError(f"fetching {what} gave HTTP {response.status}")
        body = response.read(max_bytes + 1)
        response.release_conn()
    except urllib3.exceptions.HTTPError as e:
        raise CIMDError(f"{what} couldn't be fetched ({type(e).__name__})")
    finally:
        pool.close()
    if len(body) > max_bytes:
        raise CIMDError(f"{what} is larger than {max_bytes // 1024} KB")
    return body


def _check_document(url, body):
    try:
        doc = json.loads(body)
    except ValueError:
        raise CIMDError("the client's metadata isn't JSON")
    if not isinstance(doc, dict) or doc.get('client_id') != url:
        raise CIMDError("the client's metadata doesn't name its own URL as client_id")
    name, redirect_uris = doc.get('client_name'), doc.get('redirect_uris')
    if not isinstance(name, str) or not name.strip():
        raise CIMDError("the client's metadata has no client_name")
    if not isinstance(redirect_uris, list) or not redirect_uris or not all(isinstance(u, str) for u in redirect_uris):
        raise CIMDError("the client's metadata has no redirect_uris")
    # The method it says it uses is the one it must use: a client that signs its requests can't sign in without
    # signing, or anyone with its client_id could. CIMD forbids shared secrets, so no client_secret_*
    auth_method = doc.get('token_endpoint_auth_method', 'none')
    if auth_method not in AUTH_METHODS:
        raise CIMDError(f"token_endpoint_auth_method {auth_method!r} isn't supported, only 'none' or 'private_key_jwt'")
    client = {'client_name': name.strip()[:100], 'redirect_uris': redirect_uris, 'auth_method': auth_method}
    if auth_method == 'private_key_jwt':
        jwks_uri = doc.get('jwks_uri')
        if not isinstance(jwks_uri, str) or not jwks_uri.startswith('https://'):
            raise CIMDError("the client's metadata uses private_key_jwt but has no https jwks_uri")
        # On the client_id's own host: whoever controls the metadata controls the keys anyway, and it stops a
        # metadata document from sending this server to fetch from somewhere else
        if urlsplit(jwks_uri).hostname != urlsplit(url).hostname:
            raise CIMDError("the client's jwks_uri must be on the same host as its client_id")
        client['jwks_uri'] = jwks_uri
    return client


def fetch(url):
    """{client_name, redirect_uris, auth_method[, jwks_uri]} for a CIMD client_id, cached briefly. Raises CIMDError."""
    now = time.time()
    with _cache_lock:
        cached = _cache.get(url)
    if cached and cached[0] > now:
        return cached[1]
    client = _check_document(url, _fetch_document(url))
    with _cache_lock:
        for key in [k for k, v in _cache.items() if v[0] <= now]:
            del _cache[key]
        _cache[url] = (now + CACHE_SECONDS, client)
    return client


def fetch_jwks(url, refresh=False):
    """The key set (a JWKS dict) at a client's jwks_uri, cached like documents. refresh=True fetches it again, for a
    key id that isn't in it, but at most every JWKS_REFETCH_SECONDS. Raises CIMDError."""
    now = time.time()
    with _cache_lock:
        cached = _jwks_cache.get(url)
    if cached and cached[0] > now and not (refresh and now - cached[1] >= JWKS_REFETCH_SECONDS):
        return cached[2]
    try:
        jwks = json.loads(_fetch_jwks(url))
    except ValueError:
        raise CIMDError("the client's keys aren't JSON")
    if not isinstance(jwks, dict) or not isinstance(jwks.get('keys'), list):
        raise CIMDError("the client's keys aren't a JWK set")
    with _cache_lock:
        for key in [k for k, v in _jwks_cache.items() if v[0] <= now]:
            del _jwks_cache[key]
        _jwks_cache[url] = (now + CACHE_SECONDS, now, jwks)
    return jwks
