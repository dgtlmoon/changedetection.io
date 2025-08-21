#!/usr/bin/env python3

from . util import live_server_setup
from changedetectionio import html_tools



# Unit test of the stripper
# Always we are dealing in utf-8
def test_strip_regex_text_func():
    test_content = """
    but sometimes we want to remove the lines.
    
    but 1 lines
    skip 5 lines
    really? yes man
#/not this tries weirdly formed regex or just strings starting with /
/not this
    but including 1234 lines
    igNORe-cAse text we dont want to keep    
    but not always."""


    ignore_lines = [
        "sometimes",
        "/\s\d{2,3}\s/",
        "/ignore-case text/",
        "really?",
        "/skip \d lines/i",
        "/not"
    ]

    stripped_content = html_tools.strip_ignore_text(test_content, ignore_lines)
    assert "but 1 lines" in stripped_content
    assert "igNORe-cAse text" not in stripped_content
    assert "but 1234 lines" not in stripped_content
    assert "really" not in stripped_content
    assert "not this" not in stripped_content

    # Check line number reporting
    stripped_content = html_tools.strip_ignore_text(test_content, ignore_lines, mode="line numbers")
    assert stripped_content == [2, 5, 6, 7, 8, 10]
    
    stripped_content = html_tools.strip_ignore_text(test_content, ['/but 1.+5 lines/s'])
    assert "but 1 lines" not in stripped_content
    assert "skip 5 lines" not in stripped_content
    
    stripped_content = html_tools.strip_ignore_text(test_content, ['/but 1.+5 lines/s'], mode="line numbers")
    assert stripped_content == [4, 5]
    
    stripped_content = html_tools.strip_ignore_text(test_content, ['/.+/s'])
    assert stripped_content == ""
    
    stripped_content = html_tools.strip_ignore_text(test_content, ['/.+/s'], mode="line numbers")
    assert stripped_content == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]

    stripped_content = html_tools.strip_ignore_text(test_content, ['/^.+but.+\\n.+lines$/m'])
    assert "but 1 lines" not in stripped_content
    assert "skip 5 lines" not in stripped_content

    stripped_content = html_tools.strip_ignore_text(test_content, ['/^.+but.+\\n.+lines$/m'], mode="line numbers")
    assert stripped_content == [4, 5]

    stripped_content = html_tools.strip_ignore_text(test_content, ['/^.+?\.$/m'])
    assert "but sometimes we want to remove the lines." not in stripped_content
    assert "but not always." not in stripped_content

    stripped_content = html_tools.strip_ignore_text(test_content, ['/^.+?\.$/m'], mode="line numbers")
    assert stripped_content == [2, 11]

    stripped_content = html_tools.strip_ignore_text(test_content, ['/but.+?but/ms'])
    assert "but sometimes we want to remove the lines." not in stripped_content
    assert "but 1 lines" not in stripped_content
    assert "but 1234 lines" not in stripped_content
    assert "igNORe-cAse text we dont want to keep" not in stripped_content
    assert "but not always." not in stripped_content

    stripped_content = html_tools.strip_ignore_text(test_content, ['/but.+?but/ms'], mode="line numbers")
    assert stripped_content == [2, 3, 4, 9, 10, 11]

    stripped_content = html_tools.strip_ignore_text("\n\ntext\n\ntext\n\n", ['/^$/ms'], mode="line numbers")
    assert stripped_content == [1, 2, 4, 6]

    # Check that linefeeds are preserved when there are is no matching ignores
    content = "some text\n\nand other text\n"
    stripped_content = html_tools.strip_ignore_text(content, ignore_lines)
    assert content == stripped_content
