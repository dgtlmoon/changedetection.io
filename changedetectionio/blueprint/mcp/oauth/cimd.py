"""
CIMD (OAuth Client ID Metadata Documents, draft-ietf-oauth-client-id-metadata-document-02): a client_id that is an
https URL, fetching it gives the client's metadata (name, redirect URIs). No registration, the URL is the client.

The fetch goes to a URL the client chose, so it's made safe against SSRF the way the draft requires: every address the
host resolves to must be a public one, and the connection is made to that checked address (the TLS certificate is
still verified for the hostname), so a second DNS answer can't point it somewhere else. No redirects, at most 5 KB,
only a 200 counts, a short timeout. ALLOW_IANA_RESTRICTED_ADDRESSES doesn't apply here: the draft allows no exception.

No Authlib, only urllib3 (already here through requests).
"""
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlsplit

MAX_BYTES = 5 * 1024
TIMEOUT_SECONDS = 5
# Documents are cached briefly; errors never are
CACHE_SECONDS = 300

_cache = {}
_cache_lock = threading.Lock()


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
    """The raw document at url, fetched from a checked public address. Separate from fetch() so tests can stand in."""
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
            raise CIMDError(f"fetching the client's metadata gave HTTP {response.status}")
        body = response.read(MAX_BYTES + 1)
        response.release_conn()
    except urllib3.exceptions.HTTPError as e:
        raise CIMDError(f"the client's metadata couldn't be fetched ({type(e).__name__})")
    finally:
        pool.close()
    if len(body) > MAX_BYTES:
        raise CIMDError("the client's metadata is larger than 5 KB")
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
    # Public clients only: CIMD forbids shared secrets, and private_key_jwt isn't supported here
    if doc.get('token_endpoint_auth_method', 'none') != 'none':
        raise CIMDError("only public clients (token_endpoint_auth_method 'none') can sign in")
    return {'client_name': name.strip()[:100], 'redirect_uris': redirect_uris}


def fetch(url):
    """{client_name, redirect_uris} for a CIMD client_id, cached briefly. Raises CIMDError."""
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
