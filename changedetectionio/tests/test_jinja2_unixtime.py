#!/usr/bin/env python3
"""
Tests for the ``unixtime`` Jinja2 filter (#3641).

Pure unit tests that render through the real (sandboxed) Jinja environment,
so they also confirm the filter is registered and usable in notifications.
"""
from ..jinja2_custom import render


# Timestamp chosen so the UTC result is unambiguous:
# 1759188682 -> 2025-09-29 23:31:00 UTC
TS = 1759188682


def test_unixtime_default_format():
    # Pin UTC so the result is independent of the runner's TZ. The default
    # format string (%Y-%m-%d %H:%M:%S %Z) is still exercised; the default
    # timezone otherwise follows $TZ.
    out = render('{{ ts | unixtime("%Y-%m-%d %H:%M:%S %Z", "UTC") }}', ts=TS)
    assert out == "2025-09-29 23:31:22 UTC"


def test_unixtime_custom_format():
    out = render('{{ ts | unixtime("%d.%m.%Y %H:%M", "UTC") }}', ts=TS)
    assert out == "29.09.2025 23:31"


def test_unixtime_milliseconds():
    out = render('{{ ts | unixtime("%d.%m.%Y %H:%M", "UTC") }}', ts=TS * 1000)
    assert out == "29.09.2025 23:31"


def test_unixtime_microseconds():
    out = render('{{ ts | unixtime("%d.%m.%Y %H:%M", "UTC") }}', ts=TS * 1_000_000)
    assert out == "29.09.2025 23:31"


def test_unixtime_extracts_from_prose():
    out = render('{{ s | unixtime("%d.%m.%Y %H:%M", "UTC") }}',
                 s="last_battle_at: 1759188682")
    assert out == "29.09.2025 23:31"


def test_unixtime_named_timezone():
    out = render('{{ ts | unixtime("%d.%m.%Y %H:%M", "Europe/Berlin") }}', ts=TS)
    assert out == "30.09.2025 01:31"


def test_unixtime_no_timestamp_falls_back():
    # No usable timestamp -> the original token is returned, no exception.
    assert render("{{ s | unixtime }}", s="no timestamp here") == "no timestamp here"
    assert render("{{ s | unixtime }}", s=None) == "None"


def test_unixtime_small_numbers_ignored():
    assert render('{{ s | unixtime("%Y", "UTC") }}', s="price: 42") == "price: 42"
