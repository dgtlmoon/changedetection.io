"""
Conftest for unit tests - overrides autouse fixtures from parent conftest.py
Unit tests should not require live server setup.
"""
import pytest


@pytest.fixture(scope='function', autouse=True)
def prepare_test_function():
    """Override the parent fixture that requires live_server.
    Unit tests don't need live server setup."""
    yield
