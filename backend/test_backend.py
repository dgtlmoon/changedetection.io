#!/usr/bin/python3

import pytest
import backend

# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py

# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/

@pytest.fixture
def app(request):
    app = backend.changedetection_app({'datastore_path':'./datastorexxx'})
    app.debug = True

    def teardown():
        app.config['STOP_THREADS']=True
        print("teardown")

    request.addfinalizer(teardown)

    return app.test_client()


def test_hello_world(app):
    res = app.get("/")
    # print(dir(res), res.status_code)
    assert res.status_code == 200
    assert b"IMPORT" in res.data

