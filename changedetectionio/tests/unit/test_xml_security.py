#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m pytest changedetectionio/tests/unit/test_xml_security.py

import pytest
from changedetectionio import html_tools


def _xxe_payload(file_path: str) -> str:
    return f"""<?xml version="1.0"?>
<!DOCTYPE root [
  <!ENTITY xxe SYSTEM "file://{file_path}">
]>
<root><item>&xxe;</item></root>"""


def test_xxe_not_expanded_xpath_filter(tmp_path):
    """xpath_filter must not expand external entities (CVE-2026-41895)."""
    sentinel_file = tmp_path / "sentinel.txt"
    sentinel = "xxe_sentinel_should_never_appear_in_output"
    sentinel_file.write_text(sentinel)

    result = html_tools.xpath_filter("//item", _xxe_payload(sentinel_file), is_xml=True)
    assert sentinel not in result


def test_xxe_not_expanded_xpath1_filter(tmp_path):
    """xpath1_filter must not expand external entities (CVE-2026-41895)."""
    sentinel_file = tmp_path / "sentinel.txt"
    sentinel = "xxe_sentinel_should_never_appear_in_output"
    sentinel_file.write_text(sentinel)

    result = html_tools.xpath1_filter("//item", _xxe_payload(sentinel_file), is_xml=True)
    assert sentinel not in result
