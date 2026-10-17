#!/usr/bin/env python3
# Optional flaskapi-guard integration (changedetectionio/guard.py), off unless FLASKAPI_GUARD_ENABLED=true
import itertools
import os
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request

import pytest
from flask import Flask

from changedetectionio.guard import init_guard

_counter = itertools.count(1)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CHANGEDETECTION_PY = os.path.join(REPO_ROOT, 'changedetection.py')
# close_fds=False and no cwd let subprocess use posix_spawn: fork()ing the multi-threaded xdist worker segfaulted on macOS
# Prepend, never replace: the Docker image finds its dependencies through PYTHONPATH=/usr/local
SPAWN_ENV = {**os.environ, 'PYTHONPATH': os.pathsep.join(filter(None, [REPO_ROOT, os.environ.get('PYTHONPATH')]))}


def unique_ip():
    # The guard keeps per-IP state for the life of the process, so every test uses its own client IP
    n = next(_counter) + (os.getpid() % 200) * 1000
    return f"10.{n // 65536 % 256}.{n // 256 % 256}.{n % 256}"


def make_app(monkeypatch, **env):
    monkeypatch.setenv('FLASKAPI_GUARD_ENABLED', 'true')
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    app = Flask(__name__)

    @app.route('/', methods=['GET', 'POST'])
    @app.route('/language/auto-detect', methods=['GET'])
    def index():
        return 'ok'

    init_guard(app)
    return app


def get(app, ip, path='/', **kwargs):
    return app.test_client().get(path, environ_overrides={'REMOTE_ADDR': ip}, **kwargs)


def test_disabled_never_imports_guard(datastore_path):
    # Real app wiring in a clean interpreter, switch not set
    code = textwrap.dedent(f"""
        import os, sys
        os.environ.pop('FLASKAPI_GUARD_ENABLED', None)
        from changedetectionio import store
        from changedetectionio.flask_app import changedetection_app
        ds = store.ChangeDetectionStore(datastore_path={datastore_path + '/guard-off'!r}, include_default_watches=False)
        app = changedetection_app({{'datastore_path': {datastore_path + '/guard-off'!r}, 'disable_checkver': True}}, ds)
        assert 'flaskapi_guard' not in sys.modules, 'flaskapi_guard imported while disabled'
        assert 'flaskapi_guard' not in app.extensions
        names = [f.__qualname__ for f in app.before_request_funcs[None]]
        assert not any('FlaskAPIGuard' in n for n in names), names
        print('OK', flush=True)
        os._exit(0)
    """)
    os.makedirs(datastore_path + '/guard-off', exist_ok=True)
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, close_fds=False, env=SPAWN_ENV)
    assert 'OK' in out.stdout, out.stdout + out.stderr


def test_enabled_runs_before_authentication(datastore_path):
    code = textwrap.dedent(f"""
        import os
        os.environ['FLASKAPI_GUARD_ENABLED'] = 'true'
        from changedetectionio import store
        from changedetectionio.flask_app import changedetection_app
        ds = store.ChangeDetectionStore(datastore_path={datastore_path + '/guard-on'!r}, include_default_watches=False)
        app = changedetection_app({{'datastore_path': {datastore_path + '/guard-on'!r}, 'disable_checkver': True}}, ds)
        names = [f.__qualname__ for f in app.before_request_funcs[None]]
        assert 'FlaskAPIGuard._before_request' in names and 'changedetection_app.<locals>.check_authentication' in names, names
        assert names.index('FlaskAPIGuard._before_request') < names.index('changedetection_app.<locals>.check_authentication'), names
        print('OK', flush=True)
        os._exit(0)
    """)
    os.makedirs(datastore_path + '/guard-on', exist_ok=True)
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=120, close_fds=False, env=SPAWN_ENV)
    assert 'OK' in out.stdout, out.stdout + out.stderr


def test_missing_package_fails_at_startup(monkeypatch):
    monkeypatch.setenv('FLASKAPI_GUARD_ENABLED', 'true')
    monkeypatch.setitem(sys.modules, 'flaskapi_guard', None)  # makes the import raise ImportError
    with pytest.raises(RuntimeError, match='flaskapi-guard package is not installed'):
        init_guard(Flask(__name__))


def test_rate_limit_burst(monkeypatch):
    app = make_app(monkeypatch, FLASKAPI_GUARD_RATE_LIMIT=5)
    ip = unique_ip()
    assert [get(app, ip).status_code for _ in range(7)] == [200] * 5 + [429] * 2
    # another client is unaffected
    assert get(app, unique_ip()).status_code == 200


def test_allowlist(monkeypatch):
    allowed, other = unique_ip(), unique_ip()
    app = make_app(monkeypatch, FLASKAPI_GUARD_ALLOWED_IPS=allowed)
    assert get(app, allowed).status_code == 200
    assert get(app, other).status_code == 403


def test_spoofed_xff_ignored_from_untrusted_peer(monkeypatch):
    app = make_app(monkeypatch, FLASKAPI_GUARD_RATE_LIMIT=3)
    peer = unique_ip()
    codes = [get(app, peer, headers={'X-Forwarded-For': unique_ip()}).status_code for _ in range(5)]
    assert codes == [200] * 3 + [429] * 2


def test_xff_honored_from_trusted_proxy(monkeypatch):
    app = make_app(monkeypatch, FLASKAPI_GUARD_RATE_LIMIT=2)  # default trusted proxies: loopback
    # distinct clients behind the proxy get their own budget
    assert all(get(app, '127.0.0.1', headers={'X-Forwarded-For': unique_ip()}).status_code == 200 for _ in range(6))
    same = unique_ip()
    codes = [get(app, '127.0.0.1', headers={'X-Forwarded-For': same}).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]


def test_allowlist_cannot_be_spoofed_by_untrusted_peer(monkeypatch):
    allowed = unique_ip()
    app = make_app(monkeypatch, FLASKAPI_GUARD_ALLOWED_IPS=allowed)
    assert get(app, unique_ip(), headers={'X-Forwarded-For': allowed}).status_code == 403
    assert get(app, '127.0.0.1', headers={'X-Forwarded-For': allowed}).status_code == 200


def test_attack_in_query_blocked(monkeypatch):
    app = make_app(monkeypatch)
    assert get(app, unique_ip(), '/?q=%3Cscript%3Ealert(1)%3C/script%3E').status_code == 400
    assert get(app, unique_ip(), "/?q=1'%20OR%20'1'='1'%20UNION%20SELECT%20password%20FROM%20users--").status_code == 400
    assert get(app, unique_ip(), '/?tag=abc&sort=label&order=desc').status_code == 200


def test_body_is_not_scanned(monkeypatch):
    app = make_app(monkeypatch)
    ip = unique_ip()
    # Watch settings are free text: HTML, regexes and URLs in a form post must pass
    data = {
        'url': 'http://localhost:8080/admin?x=1',
        'include_filters': '<script>alert(1)</script>',
        'extract_text': r"/(?:select|union)\s+.*from\s+\w+/i",
        'notification_body': "{{watch_url}} ../../etc/passwd <img src=x onerror=alert(1)>",
    }
    assert app.test_client().post('/', data=data, environ_overrides={'REMOTE_ADDR': ip}).status_code == 200
    assert app.test_client().post('/', json=data, environ_overrides={'REMOTE_ADDR': ip}).status_code == 200


def test_ui_paths_and_private_referer_not_flagged(monkeypatch):
    # "recon" matches /language/ and "ssrf" matches a LAN/localhost Referer: both categories are off
    app = make_app(monkeypatch)
    ip = unique_ip()
    assert get(app, ip, '/language/auto-detect', headers={'Referer': 'http://192.168.1.10:5000/'}).status_code == 200
    assert get(app, ip, '/?redirect=http://127.0.0.1/', headers={'Referer': 'http://localhost:5000/'}).status_code == 200


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def run_server(datastore_path, name, **env):
    port = free_port()
    ds = os.path.join(datastore_path, name)
    os.makedirs(ds, exist_ok=True)
    full_env = {k: v for k, v in SPAWN_ENV.items() if k not in ('PYTEST_CURRENT_TEST',)}
    full_env.update({'LISTEN_HOST': '127.0.0.1', 'FLASKAPI_GUARD_ENABLED': 'true', 'ALLOW_IANA_RESTRICTED_ADDRESSES': 'true'})
    full_env.update({k: str(v) for k, v in env.items()})
    proc = subprocess.Popen([sys.executable, CHANGEDETECTION_PY, '-p', str(port), '-d', ds], env=full_env, close_fds=False,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/static/js/csrf.js', timeout=2)
            break
        except Exception:
            time.sleep(1)
    return proc, port


def status(port, xff=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}/', headers={'X-Forwarded-For': xff} if xff else {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers


@pytest.mark.parametrize('trusted, expect_rotation_is_separate_clients', [
    ('127.0.0.1,::1', True),  # loopback is the proxy: X-Forwarded-For is the client
    ('10.255.255.1', False),  # the peer (loopback) is not a trusted proxy: X-Forwarded-For is ignored
])
def test_real_server_use_x_settings_and_guard_trust_same_proxies(datastore_path, trusted, expect_rotation_is_separate_clients):
    # Real server path: werkzeug ProxyFix (USE_X_SETTINGS) runs before the guard and would trust any peer on its own
    proc, port = run_server(datastore_path, f'xs-{trusted[:3]}', USE_X_SETTINGS=1,
                            FLASKAPI_GUARD_RATE_LIMIT=4, FLASKAPI_GUARD_TRUSTED_PROXIES=trusted)
    try:
        results = [status(port, xff=unique_ip()) for _ in range(8)]  # each from a different 'client'
        codes = [c for c, _ in results]
        if expect_rotation_is_separate_clients:
            assert codes == [200] * 8
        else:
            # (the readiness probe in run_server() already used one request of the 4)
            assert codes[:3] == [200] * 3 and set(codes[3:]) == {429}, codes
            # the rejection keeps the CORS header flask_cors adds
            assert results[-1][1].get('Access-Control-Allow-Origin') == '*'
    finally:
        proc.terminate()
        proc.wait(timeout=20)
