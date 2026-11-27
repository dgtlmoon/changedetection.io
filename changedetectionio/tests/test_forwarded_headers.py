#!/usr/bin/env python3
# USE_X_SETTINGS trusted proxies (changedetectionio/forwarded_headers.py), does not need flaskapi-guard
import pytest
from loguru import logger

from changedetectionio.forwarded_headers import restrict_forwarded_headers, restrict_proxy_fix_trust

GUARD = 'FLASKAPI_GUARD_TRUSTED_PROXIES'
OWN = 'USE_X_SETTINGS_TRUSTED_PROXIES'


def capture_warnings():
    messages = []
    return messages, logger.add(lambda m: messages.append(m.record['message']), level='WARNING')


def request(middleware, peer, forwarded='1.2.3.4'):
    environ = {'REMOTE_ADDR': peer}
    if forwarded:
        environ['HTTP_X_FORWARDED_FOR'] = forwarded
    middleware(environ, None)
    return environ


def passthrough_app():
    return lambda environ, start_response: []


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv(OWN, raising=False)
    monkeypatch.delenv(GUARD, raising=False)


def test_dropping_forwarded_headers_warns_once_naming_peer_and_setting():
    middleware = restrict_forwarded_headers(passthrough_app(), ('127.0.0.1',), 'SOME_SETTING')
    messages, sink = capture_warnings()
    try:
        environs = [request(middleware, '10.9.9.9') for _ in range(5)]
    finally:
        logger.remove(sink)
    assert all('HTTP_X_FORWARDED_FOR' not in e for e in environs)
    assert len(messages) == 1
    assert '10.9.9.9' in messages[0] and 'SOME_SETTING' in messages[0]


def test_no_warning_without_forwarded_headers_or_from_trusted_proxy():
    middleware = restrict_forwarded_headers(passthrough_app(), ('127.0.0.1',), 'SOME_SETTING')
    messages, sink = capture_warnings()
    try:
        request(middleware, '10.9.9.9', forwarded=None)
        environ = request(middleware, '127.0.0.1')
    finally:
        logger.remove(sink)
    assert environ['HTTP_X_FORWARDED_FOR'] == '1.2.3.4'
    assert messages == []


def test_cidr_ranges_and_invalid_peer():
    middleware = restrict_forwarded_headers(passthrough_app(), ('172.18.0.0/16', '::1'), 'SOME_SETTING')
    assert 'HTTP_X_FORWARDED_FOR' in request(middleware, '172.18.5.5')
    assert 'HTTP_X_FORWARDED_FOR' in request(middleware, '::1')
    assert 'HTTP_X_FORWARDED_FOR' not in request(middleware, '172.19.0.1')
    assert 'HTTP_X_FORWARDED_FOR' not in request(middleware, 'not-an-ip')


@pytest.mark.parametrize('guard_on', [True, False])
def test_own_setting_wins_and_names_itself(monkeypatch, guard_on):
    monkeypatch.setenv(OWN, '10.0.0.0/8')
    monkeypatch.setenv(GUARD, '127.0.0.1')
    middleware = restrict_proxy_fix_trust(passthrough_app(), guard_on)
    assert 'HTTP_X_FORWARDED_FOR' in request(middleware, '10.1.2.3')
    messages, sink = capture_warnings()
    try:
        assert 'HTTP_X_FORWARDED_FOR' not in request(middleware, '127.0.0.1')
    finally:
        logger.remove(sink)
    assert len(messages) == 1 and OWN in messages[0] and GUARD not in messages[0]


def test_guard_on_without_own_setting_uses_guard_proxies(monkeypatch):
    middleware = restrict_proxy_fix_trust(passthrough_app(), True)  # default 127.0.0.1,::1
    assert 'HTTP_X_FORWARDED_FOR' in request(middleware, '127.0.0.1')
    monkeypatch.setenv(GUARD, '10.255.255.1')
    middleware = restrict_proxy_fix_trust(passthrough_app(), True)
    messages, sink = capture_warnings()
    try:
        assert 'HTTP_X_FORWARDED_FOR' not in request(middleware, '127.0.0.1')
    finally:
        logger.remove(sink)
    assert len(messages) == 1 and GUARD in messages[0] and OWN not in messages[0]


def test_guard_off_without_own_setting_warns_at_startup_and_keeps_trusting_any_peer():
    app = passthrough_app()
    messages, sink = capture_warnings()
    try:
        middleware = restrict_proxy_fix_trust(app, False)
        assert len(messages) == 1  # at startup, before any request
        environ = request(middleware, '10.9.9.9')
    finally:
        logger.remove(sink)
    assert middleware is app
    assert environ['HTTP_X_FORWARDED_FOR'] == '1.2.3.4'
    assert len(messages) == 1  # and not again on requests
    assert OWN in messages[0] and 'any client' in messages[0]
