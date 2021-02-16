#!/usr/bin/python3

import pytest
import backend
from backend import store
import os
import time
import requests
# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py

# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/


def test_import(client):
    res = client.get("/")
    assert b"IMPORT" in res.data
    assert res.status_code == 200

    test_url_list = ["https://slashdot.org"]
    res = client.post('/import', data={'urls': "\n".join(test_url_list)}, follow_redirects=True)
    s = "{} Imported".format(len(test_url_list))

    #p= url_for('test_endpoint', _external=True

    assert bytes(s.encode('utf-8')) in res.data

    for url in test_url_list:
        assert bytes(url.encode('utf-8')) in res.data

    #response = requests.get('http://localhost:5000/random_string')
    #assert response.status_code == 200
    #assert response.json() == [{'id': 1}]


def test_import_a(client):
    res = client.get("/")
    assert b"IMPORT" in res.data
    assert res.status_code == 200
