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

    # Enable a BASE_URL for notifications to work (so we can look for diff/ etc URLs)
    os.environ["BASE_URL"] = "http://mysite.com/"

    # Unlink test output files
    files = ['test-datastore/output.txt',
             "{}/url-watches.json".format(datastore_path),
             'test-datastore/notification.txt']
    for file in files:
        try:
            os.unlink(file)
        except FileNotFoundError:
            pass

    app_config = {'datastore_path': datastore_path}
    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], include_default_watches=False)
    app = changedetection_app(app_config, datastore)
    app.config['STOP_THREADS'] = True

    def teardown():
        datastore.stop_thread = True
        app.config.exit.set()
        for fname in ["url-watches.json", "count.txt", "output.txt"]:
            try:
                os.unlink("{}/{}".format(datastore_path, fname))
            except FileNotFoundError:
                # This is fine in the case of a failure.
                pass

    request.addfinalizer(teardown)
    yield app

