#!/usr/bin/env python3
"""FETCH_ERROR_DNS_LOOKUP_REGEX: a failed check whose error could be a DNS problem is looked up at a public DNS
service, and reported as "Domain not found" / "Address not found" when the service definitely says so."""

from flask import url_for

from changedetectionio import fetch_error_dns_lookup as lookup
from .util import wait_for_all_checks, delete_all_watches

SOCKS_ERROR = "Exception: net::ERR_SOCKS_CONNECTION_FAILED at https://shop.example.com"
REGEX = "(ERR_SOCKS_CONNECTION_FAILED|ERR_TUNNEL_CONNECTION_FAILED)"

# Answers as dns.google gives them
NO_SUCH_DOMAIN = {"Status": 3, "Question": [{"name": "shop.example.com.", "type": 1}]}
NO_ADDRESS = {"Status": 0, "Question": [{"name": "shop.example.com.", "type": 1}]}
# A name that points on to another name which has no address: there is an answer, but it is not an address
ONLY_A_CNAME = {"Status": 0, "Answer": [{"name": "shop.example.com.", "type": 5, "data": "gone.cdn.example.net."}]}
HAS_ADDRESS = {"Status": 0, "Answer": [{"name": "shop.example.com.", "type": 1, "data": "93.184.216.34"}]}
HAS_IPV6_ADDRESS = {"Status": 0, "Answer": [{"name": "shop.example.com.", "type": 28, "data": "2606:2800:220:1::1"}]}
COULD_NOT_SAY = {"Status": 2}


def _answers(monkeypatch, a, aaaa=None):
    """The service answers `a` for the A record and `aaaa` (the same if not given) for AAAA. Returns the questions asked."""
    asked = []

    def query(hostname, record_type):
        asked.append((hostname, record_type))
        answer = a if record_type == 'A' else (aaaa if aaaa is not None else a)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(lookup, '_query', query)
    return asked


def test_off_by_default(monkeypatch):
    monkeypatch.delenv(lookup.REGEX_SETTING, raising=False)
    asked = _answers(monkeypatch, NO_SUCH_DOMAIN)
    assert lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com') is None
    assert asked == [], "Nothing is sent anywhere unless it is switched on"


def test_only_errors_matching_the_regex_are_looked_up(monkeypatch):
    monkeypatch.setenv(lookup.REGEX_SETTING, REGEX)
    asked = _answers(monkeypatch, NO_SUCH_DOMAIN)
    assert lookup.explain_fetch_error("Exception: net::ERR_CERT_DATE_INVALID at https://shop.example.com", 'https://shop.example.com') is None
    assert asked == []
    assert lookup.explain_fetch_error("Exception: net::ERR_TUNNEL_CONNECTION_FAILED at https://shop.example.com", 'https://shop.example.com')
    assert asked == [('shop.example.com', 'A')]

    # A setting that is not a regex switches it off, it does not break the check
    monkeypatch.setenv(lookup.REGEX_SETTING, '(unclosed')
    assert lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com') is None


def test_a_definite_no_is_reported_as_the_error(monkeypatch):
    monkeypatch.setenv(lookup.REGEX_SETTING, REGEX)

    _answers(monkeypatch, NO_SUCH_DOMAIN)
    error = lookup.explain_fetch_error(SOCKS_ERROR, 'https://Shop.Example.com:8443/deals?x=1')
    assert error.startswith("Domain not found - 'shop.example.com' does not exist")
    assert SOCKS_ERROR in error, "What the browser said is kept after it"

    # The name is there, an address is not: asked for both kinds before saying so
    asked = _answers(monkeypatch, NO_ADDRESS)
    error = lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com')
    assert error.startswith("Address not found - 'shop.example.com' has no DNS address")
    assert asked == [('shop.example.com', 'A'), ('shop.example.com', 'AAAA')]

    _answers(monkeypatch, ONLY_A_CNAME)
    assert lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com').startswith("Address not found")


def test_anything_else_leaves_the_error_alone(monkeypatch):
    monkeypatch.setenv(lookup.REGEX_SETTING, REGEX)
    for what, a, aaaa in (
            ("it has an address", HAS_ADDRESS, None),
            ("it has only an IPv6 address", NO_ADDRESS, HAS_IPV6_ADDRESS),
            ("the service could not say", COULD_NOT_SAY, None),
            ("the service could not say for IPv6", NO_ADDRESS, COULD_NOT_SAY),
            ("the lookup failed", ConnectionError("no route"), None),
            ("the lookup failed half way", NO_ADDRESS, TimeoutError("timed out")),
            ("the answer is not what was expected", {}, None),
    ):
        _answers(monkeypatch, a, aaaa)
        assert lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com') is None, what

    # Nothing the public DNS could know about is asked for
    asked = _answers(monkeypatch, NO_SUCH_DOMAIN)
    for url in ('http://192.168.1.10/status', 'http://[2001:db8::1]/', 'http://intranet/page', 'http://localhost:5000/', '', None, 'not a url'):
        assert lookup.explain_fetch_error(SOCKS_ERROR, url) is None, url
    assert asked == []


def test_the_request_to_the_service(monkeypatch):
    """What is sent: the name and the record type, to dns.google unless another service is set"""
    import requests
    sent = []

    class Reply:
        def raise_for_status(self):
            pass

        def json(self):
            return NO_SUCH_DOMAIN

    def get(url, **kwargs):
        sent.append((url, kwargs))
        return Reply()

    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setenv(lookup.REGEX_SETTING, REGEX)
    monkeypatch.delenv(lookup.URL_SETTING, raising=False)
    assert lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com').startswith('Domain not found')
    url, kwargs = sent[0]
    assert url == 'https://dns.google/resolve'
    assert kwargs['params'] == {'name': 'shop.example.com', 'type': 'A'}
    assert kwargs['timeout'] == lookup.LOOKUP_TIMEOUT_SECONDS and kwargs['headers'] == {'accept': 'application/dns-json'}

    monkeypatch.setenv(lookup.URL_SETTING, 'https://cloudflare-dns.com/dns-query')
    lookup.explain_fetch_error(SOCKS_ERROR, 'https://shop.example.com')
    assert sent[-1][0] == 'https://cloudflare-dns.com/dns-query'


def test_a_failing_check_shows_it(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Through a real check: the watch's error is the one from the lookup, and without the setting it is not"""
    datastore = client.application.config.get('DATASTORE')
    asked = _answers(monkeypatch, NO_SUCH_DOMAIN)

    # A name that cannot resolve, so the check fails with the fetcher's own "could not resolve"
    monkeypatch.delenv(lookup.REGEX_SETTING, raising=False)
    without = datastore.add_watch(url='https://shop.does-not-exist-cdio.invalid/deals')
    client.get(url_for("ui.form_watch_checknow", uuid=without), follow_redirects=True)
    wait_for_all_checks(client)
    plain = datastore.data['watching'][without]['last_error']
    assert plain and plain.startswith('Exception: ') and 'not found' not in plain
    assert asked == [], "Nothing was looked up"

    monkeypatch.setenv(lookup.REGEX_SETTING, r"(NameResolutionError|Failed to resolve|Name or service not known)")
    uuid = datastore.add_watch(url='https://other.does-not-exist-cdio.invalid/deals')
    client.get(url_for("ui.form_watch_checknow", uuid=uuid), follow_redirects=True)
    wait_for_all_checks(client)
    error = datastore.data['watching'][uuid]['last_error']
    assert error.startswith("Domain not found - 'other.does-not-exist-cdio.invalid' does not exist"), error
    assert asked == [('other.does-not-exist-cdio.invalid', 'A')]
    # And it is what the watch list shows
    assert b'Domain not found' in client.get(url_for("watchlist.index")).data

    delete_all_watches(client)
