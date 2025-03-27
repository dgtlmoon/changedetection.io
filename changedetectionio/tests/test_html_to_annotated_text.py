#!/usr/bin/env python3
"""Test suite for the method to extract annotated text from an HTML string"""
from ..html_tools import html_to_annotated_text

test_html = """<html>
       <head><title>Title<title></head>
       <body>
         Some initial text<br>
         <p>Which is across multiple lines</p>
         <a href="/first_link"> More Text </a>
         <br>
         So let's see what happens.  <br>
         <a href="second_link.com"> Even More Text </a>
         <p class="item">This is an item with title <span class="test">Item Title</span></p>
       </body>
    </html>
    """

test_annotation_rules = {
    "a": ["hyperlink", "a"],
    "span[class*='test']": ["item-title"],
    "p[class*='item']": ["item"]
}

def test_html_to_annotated_text_func():
    annotated_xml = html_to_annotated_text(test_html, test_annotation_rules)

    expected_annotated_xml = (
        '<text>Title\n'
        'Some initial text\n'
        'Which is across multiple lines\n'
        '<hyperlink><a>More Text</a></hyperlink>\n'
        "So let's see what happens.\n"
        '<hyperlink><a>Even More Text</a></hyperlink><item>\n'
        'This is an item with title<item-title>Item Title</item-title>\n'
        '</item></text>'
    )

    assert annotated_xml == expected_annotated_xml


def test_html_to_annotated_text_func_block_newlines():
    annotated_no_block_newlines = html_to_annotated_text(
        test_html,
        test_annotation_rules,
        insert_block_newlines=True,
        strip_edge_whitespace=False,
        collapse_whitespace=False,
        normalize_whitespace=False
    )

    expected_no_block_newlines = (
        '<text>\n'
        'Title\n'
        '\n'
        '\n'
        '         Some initial text\n'
        '\n'
        'Which is across multiple lines\n'
        '\n'
        '<hyperlink><a> More Text </a></hyperlink>\n'
        '\n'
        "         So let's see what happens.  \n"
        '\n'
        '<hyperlink><a> Even More Text </a></hyperlink>\n'
        '<item>This is an item with title <item-title>Item Title</item-title>\n'
        '</item>\n'
        '\n'
        '\n'
        '</text>'
    )
    assert annotated_no_block_newlines == expected_no_block_newlines

def test_html_to_annotated_text_func_strip_edge_whitespace():
    annotated_no_collapse = html_to_annotated_text(
        test_html,
        test_annotation_rules,
        insert_block_newlines=False,
        strip_edge_whitespace=True,
        collapse_whitespace=False,
        normalize_whitespace=False
    )

    expected_no_collapse = (
        '<text>\n'
        'Title\n'
        '\n'
        '         Some initial text\n'
        'Which is across multiple lines\n'
        '<hyperlink><a>More Text</a></hyperlink>\n'
        '\n'
        "         So let's see what happens.\n"
        '<hyperlink><a>Even More Text</a></hyperlink>\n'
        '<item>This is an item with title<item-title>Item Title</item-title></item>\n'
        '\n'
        '\n'
        '</text>'
    )
    assert annotated_no_collapse == expected_no_collapse

def test_html_to_annotated_text_func_collapse_whitespace():
    annotated_no_collapse = html_to_annotated_text(
        test_html,
        test_annotation_rules,
        insert_block_newlines=False,
        strip_edge_whitespace=False,
        collapse_whitespace=True,
        normalize_whitespace=False
    )

    expected_no_collapse = (
        '<text>TitleSome initial textWhich is across multiple lines<hyperlink><a>More '
        "Text</a></hyperlink>So let's see what happens.<hyperlink><a>Even More "
        'Text</a></hyperlink><item>This is an item with title<item-title>Item '
        'Title</item-title></item></text>'
    )
    assert annotated_no_collapse == expected_no_collapse

def test_html_to_annotated_text_func_normalize_whitespace():
    annotated_no_normalize = html_to_annotated_text(
        test_html,
        test_annotation_rules,
        insert_block_newlines=False,
        strip_edge_whitespace=False,
        collapse_whitespace=False,
        normalize_whitespace=True
    )
    expected_no_normalize = (
        '<text> Title           Some initial text Which is across multiple lines '
        "<hyperlink><a> More Text </a></hyperlink>           So let's see what "
        'happens.   <hyperlink><a> Even More Text </a></hyperlink> <item>This is an '
        'item with title <item-title>Item Title</item-title></item>   </text>'
    )
    assert annotated_no_normalize == expected_no_normalize

def test_html_to_annotated_text_func_all_off():
    annotated_no_normalize = html_to_annotated_text(
        test_html,
        test_annotation_rules,
        insert_block_newlines=False,
        strip_edge_whitespace=False,
        collapse_whitespace=False,
        normalize_whitespace=False
    )
    expected_no_normalize = (
        '<text>\n'
        'Title\n'
        '\n'
        '         Some initial text\n'
        'Which is across multiple lines\n'
        '<hyperlink><a> More Text </a></hyperlink>\n'
        '\n'
        "         So let's see what happens.  \n"
        '<hyperlink><a> Even More Text </a></hyperlink>\n'
        '<item>This is an item with title <item-title>Item Title</item-title></item>\n'
        '\n'
        '\n'
        '</text>'
    )
    assert annotated_no_normalize == expected_no_normalize