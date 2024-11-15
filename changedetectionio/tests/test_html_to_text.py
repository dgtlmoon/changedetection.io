#!/usr/bin/env python3
"""Test suite for the method to extract text from an html string"""
from ..html_tools import html_to_text


def test_html_to_text_func():
    test_html = """<html>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <a href="/first_link"> More Text </a>
     <br>
     So let's see what happens.  <br>
     <a href="second_link.com"> Even More Text </a>
     </body>
     </html>
    """

    # extract text, with 'render_anchor_tag_content' set to False
    text_content = html_to_text(test_html, render_anchor_tag_content=False)

    no_links_text = \
        "Some initial text\n\nWhich is across multiple " \
        "lines\n\nMore Text\nSo let's see what happens.\nEven More Text"

    # check that no links are in the extracted text
    assert text_content == no_links_text

    # extract text, with 'render_anchor_tag_content' set to True
    text_content = html_to_text(test_html, render_anchor_tag_content=True)

    links_text = \
        "Some initial text\n\nWhich is across multiple lines\n\n[ More Text " \
        "](/first_link)\nSo let's see what happens.\n[ Even More Text ]" \
        "(second_link.com)"

    # check that links are present in the extracted text
    assert text_content == links_text
