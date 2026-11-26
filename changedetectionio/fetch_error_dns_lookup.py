"""When a check fails with an error that could be a DNS problem, look the address up and say so if it is one.

A browser behind a proxy cannot tell: the proxy does the lookup and Chrome reports every failure of it the same way
(net::ERR_SOCKS_CONNECTION_FAILED, net::ERR_TUNNEL_CONNECTION_FAILED), whether the site is down, the proxy is, or
the address does not exist. So the name is asked for at a public DNS-over-HTTPS service, and only a definite "no"
changes the error:

  "Domain not found"   the name does not exist (NXDOMAIN)
  "Address not found"  the name exists but has no address (no A and no AAAA record, also after following a CNAME)

Anything else (it resolves, the lookup failed or timed out, the service was unsure) leaves the error as it was.

Off unless FETCH_ERROR_DNS_LOOKUP_REGEX is set, since it sends the hostname of the failing watch to the service:

  FETCH_ERROR_DNS_LOOKUP_REGEX  a regex, searched for in the error text. A match is what starts the lookup, e.g.
                                (ERR_SOCKS_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED|ERR_NAME_NOT_RESOLVED)
  FETCH_ERROR_DNS_LOOKUP_URL    the service, default https://dns.google/resolve (any with the same JSON answers,
                                e.g. https://cloudflare-dns.com/dns-query)
"""
import ipaddress
import os
import re
from urllib.parse import urlparse

from loguru import logger

REGEX_SETTING = 'FETCH_ERROR_DNS_LOOKUP_REGEX'
URL_SETTING = 'FETCH_ERROR_DNS_LOOKUP_URL'
DEFAULT_LOOKUP_URL = 'https://dns.google/resolve'
LOOKUP_TIMEOUT_SECONDS = 5

# DNS answer codes and record types, as numbers in the JSON
NOERROR, NXDOMAIN = 0, 3
RECORD_A, RECORD_AAAA = 1, 28

DOMAIN_NOT_FOUND = 'domain not found'
ADDRESS_NOT_FOUND = 'address not found'


def _lookup_regex():
    """The compiled FETCH_ERROR_DNS_LOOKUP_REGEX, None when unset or not a regex"""
    pattern = (os.getenv(REGEX_SETTING) or '').strip()
    if not pattern:
        return None
    try:
        return re.compile(pattern)
    except re.error as e:
        logger.warning(f"{REGEX_SETTING} is not a valid regex ({e}), DNS lookup of failing checks is off")
        return None


def _hostname_to_look_up(url):
    """The hostname of the URL if it is a name the public DNS could know: not an IP address, not a single label"""
    try:
        hostname = (urlparse(url or '').hostname or '').strip('.').lower()
    except ValueError:
        return None
    if not hostname or '.' not in hostname:
        return None
    try:
        ipaddress.ip_address(hostname)
        return None
    except ValueError:
        return hostname


def _query(hostname, record_type):
    """One question to the service, its JSON answer. Raises on anything but a JSON answer."""
    import requests
    r = requests.get(os.getenv(URL_SETTING) or DEFAULT_LOOKUP_URL,
                     params={'name': hostname, 'type': record_type},
                     headers={'accept': 'application/dns-json'},
                     timeout=LOOKUP_TIMEOUT_SECONDS)
    r.raise_for_status()
    return r.json()


def dns_verdict(hostname):
    """DOMAIN_NOT_FOUND or ADDRESS_NOT_FOUND when the service definitely says so, else None (it has an address, or
    there is no telling)."""
    try:
        has_no_address = 0
        for record_type, number in (('A', RECORD_A), ('AAAA', RECORD_AAAA)):
            answer = _query(hostname, record_type)
            status = answer.get('Status')
            if status == NXDOMAIN:
                return DOMAIN_NOT_FOUND
            if status != NOERROR:
                # SERVFAIL, refused ...: the service could not say
                return None
            # A CNAME on the way is in the answers too, only an address counts
            if any(a.get('type') == number for a in answer.get('Answer') or []):
                return None
            has_no_address += 1
        return ADDRESS_NOT_FOUND if has_no_address == 2 else None
    except Exception as e:
        logger.debug(f"DNS lookup of '{hostname}' for a failing check did not give an answer: {e}")
        return None


def explain_fetch_error(error_text, url):
    """The error to show in place of `error_text` when it is one to look into (FETCH_ERROR_DNS_LOOKUP_REGEX) and the
    address of `url` definitely does not exist. None to keep the error as it is. Does a network request: call it
    off the event loop."""
    regex = _lookup_regex()
    if not regex or not error_text or not regex.search(str(error_text)):
        return None
    hostname = _hostname_to_look_up(url)
    if not hostname:
        return None
    verdict = dns_verdict(hostname)
    if verdict == DOMAIN_NOT_FOUND:
        return f"Domain not found - '{hostname}' does not exist (DNS lookup) - {error_text}"
    if verdict == ADDRESS_NOT_FOUND:
        return f"Address not found - '{hostname}' has no DNS address (DNS lookup) - {error_text}"
    return None
