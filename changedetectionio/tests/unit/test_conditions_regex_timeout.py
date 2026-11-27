#!/usr/bin/env python3
"""The 'matches regex' conditions search the watched page's text, so the search has a time limit."""
import time

import pytest

from changedetectionio.conditions import default_plugin
from changedetectionio.jinja2_custom.plugins import regex as regex_plugin


@pytest.fixture
def operators():
    return default_plugin.register_operators()


def test_regex_conditions_still_match(operators):
    assert operators['contains_regex'](None, "Price now 12.50 EUR", r"\d+\.\d+ eur") is True
    assert operators['contains_regex'](None, "Sold out", r"\d+\.\d+ eur") is False
    assert operators['!contains_regex'](None, "Sold out", r"\d+\.\d+ eur") is True
    assert operators['!contains_regex'](None, "Price now 12.50 EUR", r"\d+\.\d+ eur") is False


def test_regex_condition_that_backtracks_forever_is_stopped(operators, monkeypatch):
    monkeypatch.setattr(regex_plugin, 'REGEX_TIMEOUT_SECONDS', 1)
    page_text = "a" * 5000 + "b"

    for operator in ('contains_regex', '!contains_regex'):
        started = time.time()
        # Not "found" and not "not found": the check fails and says why
        with pytest.raises(TimeoutError, match="took longer than 1 seconds"):
            operators[operator](None, page_text, "(a+)+$")
        assert time.time() - started < 8
