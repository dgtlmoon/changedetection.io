#!/usr/bin/python3

import pytest
from backend import changedetection_app
from backend import store
import os


# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py
# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/

global app

@pytest.fixture(scope='session')
def app(request):
    """Create application for the tests."""
    datastore_path = "./test-datastore"

    try:
        os.mkdir(datastore_path)
    except FileExistsError:
        pass

    try:
        os.unlink("{}/url-watches.json".format(datastore_path))
    except FileNotFoundError:
        pass

    app_config = {'datastore_path': datastore_path}
    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], include_default_watches=False)
    app = changedetection_app(app_config, datastore)

    def teardown():
        datastore.stop_thread = True
        app.config['STOP_THREADS'] = True
        try:
            os.unlink("{}/url-watches.json".format(datastore_path))
        except FileNotFoundError:
            # This is fine in the case of a failure.
            pass

        @live_server.app.route('/test-endpoint')
        def test_endpoint():
            # Tried using a global var here but didn't seem to work, so reading from a file instead.
            with open("test-datastore/output.txt", "r") as f:
                return f.read()

        live_server.start()

        assert 1 == 1

    request.addfinalizer(teardown)
    yield app

