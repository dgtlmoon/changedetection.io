#!/usr/bin/python3

import pytest
from webtest import TestApp
from backend import changedetection_app
from backend import store
import os


# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py

# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/


@pytest.fixture(scope='session')
def app(request):
    """Create application for the tests."""

    datastore_path = "./test-datastore"
    app_config = {'datastore_path': datastore_path}
    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'])
    _app = changedetection_app(app_config, datastore)

    # Establish an application context before running the tests.
    ctx = _app.app_context()
    ctx.push()

    def teardown():
        ctx.pop()

    request.addfinalizer(teardown)
    return _app

@pytest.fixture(scope='session')
def client(app):
    return app.test_client()

@pytest.fixture(scope='function')
def session(request):
    """Creates a new database session for a test."""
    return session
