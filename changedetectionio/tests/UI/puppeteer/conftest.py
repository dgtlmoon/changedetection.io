#!/usr/bin/env python3

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import requests

from ... import conftest
from . import browser

# Next to the test server of the other tests (--live-server-port, 5004 in CI)
APP_PORT = int(os.getenv('UI_TEST_APP_PORT', 5005))


@pytest.fixture(scope='session')
def running_app(tmp_path_factory):
    """The application itself, started the way it is on a server (changedetection.py), with an empty datastore.

    The test server the other tests use is a copy of the test process without its worker threads, good for
    serving a page to fetch but not for a browser that adds and saves watches on it. All watches are paused
    (-P), so nothing is fetched from the internet.

    The browser runs in another container and reaches the application by this container's hostname.
    """
    if not os.getenv('PLAYWRIGHT_DRIVER_URL'):
        pytest.skip("Needs a browser to drive, set PLAYWRIGHT_DRIVER_URL (ws://sockpuppetbrowser:3000)")

    datastore_path = tmp_path_factory.mktemp('ui-test-datastore')
    log_path = datastore_path / 'app.log'
    env = dict(os.environ)
    # Set for the other tests' test server, here it would put the wrong host in the application's own links
    env.pop('FLASK_SERVER_NAME', None)

    repo_root = Path(__file__).resolve().parents[4]
    with open(log_path, 'w') as log:
        process = subprocess.Popen(
            [sys.executable, str(repo_root / 'changedetection.py'), '-d', str(datastore_path), '-p', str(APP_PORT), '-h', '0.0.0.0', '-P', 'true'],
            cwd=str(repo_root), env=env, stdout=log, stderr=subprocess.STDOUT)

    try:
        deadline = time.time() + 60
        while True:
            if process.poll() is not None:
                pytest.fail(f"The application stopped while starting:\n{log_path.read_text()[-3000:]}")
            try:
                if requests.get(f"http://127.0.0.1:{APP_PORT}/", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                pytest.fail(f"The application did not answer on port {APP_PORT} within a minute:\n{log_path.read_text()[-3000:]}")
            time.sleep(0.3)

        browser.APP_URL = f"http://{socket.gethostname()}:{APP_PORT}"
        yield browser.APP_URL
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
