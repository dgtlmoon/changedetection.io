#!/usr/bin/env python3
"""Test suite for the method to sort annotated text with css selector pairs"""
from ..html_tools import html_to_annotated_text, sort_annotated_text_by_selectors

def test_sort_annotated_text():
    # Minimal HTML: two 'outer' divs, each containing 'inner' spans
    # that have a 'name' child. The ordering is B,A and D,C so we
    # expect it to become A,B and C,D after sorting by name text.
    test_html = """
        <html>
          <body>
            <div class="outer">
                <span class="inner">Y-Item <span class="name">B</span></span>
                <span class="inner">Z-Item <span class="name">A</span></span>
            </div>
            <div class="outer">
                <span class="inner">W-Item <span class="name">D</span></span>
                <span class="inner">X-Item <span class="name">C</span></span>
            </div>
          </body>
        </html>
        """

    # Annotation rules: outer, inner, name
    test_annotation_rules = \
    {
        "div[class*='outer']": ["outer"],
        "span[class*='inner']": ["inner"],
        "span[class*='name']": ["name"]
    }

    # Convert HTML to annotated text
    annotated_xml = html_to_annotated_text(
        test_html,
        test_annotation_rules
    )

    # We'll test the same sorting logic with three different selector approaches:
    # 1) CSS
    # 2) XPath (note the second part is .// to stay within context)
    # 3) xpath1
    selector_groups = [
        [("outer", ""), ("outer > inner", "name")],  # CSS direct child
        [("//outer", ""), ("//inner", "xpath:.//name")],  # XPath
        [("xpath1://outer", ""), ("xpath1://outer/inner", "xpath1:.//name")]  # xpath1
    ]

    # The expected order after sorting each 'outer' group by its 'name' text:
    # First <div.outer>: (A, B) instead of (B, A)
    # Second <div.outer>: (C, D) instead of (D, C)
    expected_annotated_xml = (
        '<text><outer><inner>Z-Item<name>A</name></inner>\n'
        '<inner>Y-Item<name>B</name></inner></outer><outer><inner>X-Item<name>C</name></inner>\n'
        '<inner>W-Item<name>D</name></inner></outer></text>'
    )

    # Check sorting with each selector approach:
    for selectors in selector_groups:
        sorted_annotated_xml = sort_annotated_text_by_selectors(annotated_xml, selectors)

        assert sorted_annotated_xml == expected_annotated_xml, (
            f"Sorting failed for selectors: {selectors}\n"
            f"Got:\n{sorted_annotated_xml}\n"
            f"Expected:\n{expected_annotated_xml}"
        )
