#!/usr/bin/python3

from . util import live_server_setup
from changedetectionio import html_tools

def test_setup(live_server):
    live_server_setup(live_server)

# Unit test of the stripper
# Always we are dealing in utf-8
def test_strip_regex_text_func():
    from ..fetch_processor import json_html_plaintext

    test_content = """
    but sometimes we want to remove the lines.
    
    but 1 lines
    but including 1234 lines
    igNORe-cAse text we dont want to keep    
    but not always."""

    ignore_lines = ["sometimes", "/\s\d{2,3}\s/", "/ignore-case text/"]

    fetcher = json_html_plaintext.perform_site_check(datastore=False)
    stripped_content = html_tools.strip_ignore_text(test_content, ignore_lines)

    assert b"but 1 lines" in stripped_content
    assert b"igNORe-cAse text" not in stripped_content
    assert b"but 1234 lines" not in stripped_content

