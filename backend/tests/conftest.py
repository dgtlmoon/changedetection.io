#!/usr/bin/python3

import pytest
from backend import changedetection_app
from backend import store


# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py

# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/

global app


@pytest.fixture(scope='session')
def app(request):
    """Create application for the tests."""

    datastore_path = "./test-datastore"

    import os
    try:
        os.mkdir(datastore_path)
    except FileExistsError:
        pass


    try:
        os.unlink("{}/url-watches.json".format(datastore_path))
    except FileNotFoundError:
        pass


    app_config = {'datastore_path': datastore_path}
    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'])
    app = changedetection_app(app_config, datastore)

    # Establish an application context before running the tests.
    #ctx = _app.app_context()
    #ctx.push()

    def teardown():
        datastore.stop_thread = True
        app.config['STOP_THREADS']= True

    request.addfinalizer(teardown)
    return app

#@pytest.fixture(scope='session')
#def client(app):
#    with app.test_client() as client:
#        yield client


