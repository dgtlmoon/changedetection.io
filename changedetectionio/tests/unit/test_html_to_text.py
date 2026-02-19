#!/usr/bin/env python3
# coding=utf-8

"""Unit tests for html_tools.html_to_text function."""

import hashlib
import threading
import unittest
from queue import Queue

from changedetectionio.html_tools import html_to_text


class TestHtmlToText(unittest.TestCase):
    """Test html_to_text function for correctness and thread-safety."""

    def test_basic_text_extraction(self):
        """Test basic HTML to text conversion."""
        html = '<html><body><h1>Title</h1><p>Paragraph text.</p></body></html>'
        text = html_to_text(html)

        assert 'Title' in text
        assert 'Paragraph text.' in text
        assert '<' not in text  # HTML tags should be stripped
        assert '>' not in text

    def test_empty_html(self):
        """Test handling of empty HTML."""
        html = '<html><body></body></html>'
        text = html_to_text(html)

        # Should return empty or whitespace only
        assert text.strip() == ''

    def test_nested_elements(self):
        """Test extraction from nested HTML elements."""
        html = '''
        <html>
            <body>
                <div>
                    <h1>Header</h1>
                    <div>
                        <p>First paragraph</p>
                        <p>Second paragraph</p>
                    </div>
                </div>
            </body>
        </html>
        '''
        text = html_to_text(html)

        assert 'Header' in text
        assert 'First paragraph' in text
        assert 'Second paragraph' in text

    def test_anchor_tag_rendering(self):
        """Test anchor tag rendering option."""
        html = '<html><body><a href="https://example.com">Link text</a></body></html>'

        # Without rendering anchors
        text_without = html_to_text(html, render_anchor_tag_content=False)
        assert 'Link text' in text_without
        assert 'https://example.com' not in text_without

        # With rendering anchors
        text_with = html_to_text(html, render_anchor_tag_content=True)
        assert 'Link text' in text_with
        assert 'https://example.com' in text_with or '[Link text]' in text_with

    def test_rss_mode(self):
        """Test RSS mode converts title tags to h1."""
        html = '<item><title>RSS Title</title><description>Content</description></item>'

        # is_rss=True should convert <title> to <h1>
        text = html_to_text(html, is_rss=True)

        assert 'RSS Title' in text
        assert 'Content' in text

    def test_special_characters(self):
        """Test handling of special characters and entities."""
        html = '<html><body><p>Test &amp; &lt;special&gt; characters</p></body></html>'
        text = html_to_text(html)

        # Entities should be decoded
        assert 'Test &' in text or 'Test &amp;' in text
        assert 'special' in text

    def test_whitespace_handling(self):
        """Test that whitespace is properly handled."""
        html = '<html><body><p>Line 1</p><p>Line 2</p></body></html>'
        text = html_to_text(html)

        # Should have some separation between lines
        assert 'Line 1' in text
        assert 'Line 2' in text
        assert text.count('\n') >= 1  # At least one newline

    def test_deterministic_output(self):
        """Test that the same HTML always produces the same text."""
        html = '<html><body><h1>Test</h1><p>Content here</p></body></html>'

        # Extract text multiple times
        results = [html_to_text(html) for _ in range(10)]

        # All results should be identical
        assert len(set(results)) == 1, "html_to_text should be deterministic"

    def test_thread_safety_determinism(self):
        """
        Test that html_to_text produces deterministic output under high concurrency.

        This verifies that lxml's default parser (used by inscriptis.get_text)
        is thread-safe and produces consistent results when called from multiple
        threads simultaneously.
        """
        html = '''
        <html>
            <head><title>Test Page</title></head>
            <body>
                <h1>Main Heading</h1>
                <div class="content">
                    <p>First paragraph with <b>bold text</b>.</p>
                    <p>Second paragraph with <i>italic text</i>.</p>
                    <ul>
                        <li>Item 1</li>
                        <li>Item 2</li>
                        <li>Item 3</li>
                    </ul>
                </div>
            </body>
        </html>
        '''

        results_queue = Queue()

        def worker(worker_id, iterations=10):
            """Worker that converts HTML to text multiple times."""
            for i in range(iterations):
                text = html_to_text(html)
                md5 = hashlib.md5(text.encode('utf-8')).hexdigest()
                results_queue.put((worker_id, i, md5))

        # Launch many threads simultaneously
        num_threads = 50
        threads = []

        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Collect all MD5 results
        md5_values = []
        while not results_queue.empty():
            _, _, md5 = results_queue.get()
            md5_values.append(md5)

        # All MD5s should be identical
        unique_md5s = set(md5_values)

        assert len(unique_md5s) == 1, (
            f"Thread-safety issue detected! Found {len(unique_md5s)} different MD5 values: {unique_md5s}. "
            "The thread-local parser fix may not be working correctly."
        )

        print(f"✓ Thread-safety test passed: {len(md5_values)} conversions, all identical")

    def test_thread_safety_basic(self):
        """Verify basic thread safety - multiple threads can call html_to_text simultaneously."""
        results = []
        errors = []

        def worker():
            """Worker that converts HTML to text."""
            try:
                html = '<html><body><h1>Test</h1><p>Content</p></body></html>'
                text = html_to_text(html)
                results.append(text)
            except Exception as e:
                errors.append(e)

        # Launch 10 threads simultaneously
        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have no errors
        assert len(errors) == 0, f"Thread-safety errors occurred: {errors}"

        # All results should be identical
        assert len(set(results)) == 1, "All threads should produce identical output"

        print(f"✓ Basic thread-safety test passed: {len(results)} threads, no errors")

    def test_large_html_with_bloated_head(self):
        """
        Test that html_to_text can handle large HTML documents with massive <head> bloat.

        SPAs often dump 10MB+ of styles, scripts, and other bloat into the <head> section.
        This can cause inscriptis to silently exit when processing very large documents.
        The fix strips <style>, <script>, <svg>, <noscript>, <link>, <meta>, and HTML comments
        before processing, allowing extraction of actual body content.
        """
        # Generate massive style block (~5MB)
        large_style = '<style>' + '.class{color:red;}\n' * 200000 + '</style>\n'

        # Generate massive script block (~5MB)
        large_script = '<script>' + 'console.log("bloat");\n' * 200000 + '</script>\n'

        # Generate lots of SVG bloat (~3MB)
        svg_bloat = '<svg><path d="M0,0 L100,100"/></svg>\n' * 50000

        # Generate meta/link tags (~2MB)
        meta_bloat = '<meta name="description" content="bloat"/>\n' * 50000
        link_bloat = '<link rel="stylesheet" href="bloat.css"/>\n' * 50000

        # Generate HTML comments (~1MB)
        comment_bloat = '<!-- This is bloat -->\n' * 50000

        # Generate noscript bloat
        noscript_bloat = '<noscript>Enable JavaScript</noscript>\n' * 10000

        # Build the large HTML document
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Test Page</title>
    {large_style}
    {large_script}
    {svg_bloat}
    {meta_bloat}
    {link_bloat}
    {comment_bloat}
    {noscript_bloat}
</head>
<body>
    <h1>Important Heading</h1>
    <p>This is the actual content that should be extracted.</p>
    <div>
        <p>First paragraph with meaningful text.</p>
        <p>Second paragraph with more content.</p>
    </div>
    <footer>Footer text</footer>
</body>
</html>
'''

        # Verify the HTML is actually large (should be ~20MB+)
        html_size_mb = len(html) / (1024 * 1024)
        assert html_size_mb > 15, f"HTML should be >15MB, got {html_size_mb:.2f}MB"

        print(f"  Testing {html_size_mb:.2f}MB HTML document with bloated head...")

        # This should not crash or silently exit
        text = html_to_text(html)

        # Verify we got actual text output (not empty/None)
        assert text is not None, "html_to_text returned None"
        assert len(text) > 0, "html_to_text returned empty string"

        # Verify the actual body content was extracted
        assert 'Important Heading' in text, "Failed to extract heading"
        assert 'actual content that should be extracted' in text, "Failed to extract paragraph"
        assert 'First paragraph with meaningful text' in text, "Failed to extract first paragraph"
        assert 'Second paragraph with more content' in text, "Failed to extract second paragraph"
        assert 'Footer text' in text, "Failed to extract footer"

        # Verify bloat was stripped (output should be tiny compared to input)
        text_size_kb = len(text) / 1024
        assert text_size_kb < 1, f"Output too large ({text_size_kb:.2f}KB), bloat not stripped"

        # Verify no CSS, script content, or SVG leaked through
        assert 'color:red' not in text, "Style content leaked into text output"
        assert 'console.log' not in text, "Script content leaked into text output"
        assert '<path' not in text, "SVG content leaked into text output"
        assert 'bloat.css' not in text, "Link href leaked into text output"

        print(f"  ✓ Successfully processed {html_size_mb:.2f}MB HTML -> {text_size_kb:.2f}KB text")

    def test_body_display_none_spa_pattern(self):
        """
        Test that html_to_text can extract content from pages with display:none body.

        SPAs (Single Page Applications) often use <body style="display:none"> to hide content
        until JavaScript loads and renders the page. inscriptis respects CSS display rules,
        so without preprocessing, it would skip all content and return only newlines.

        The fix strips display:none and visibility:hidden styles from the body tag before
        processing, allowing text extraction from client-side rendered applications.
        """
        # Test case 1: Basic display:none
        html1 = '''<!DOCTYPE html>
<html lang="en">
<head><title>What's New – Fluxguard</title></head>
<body style="display:none">
    <h1>Important Heading</h1>
    <p>This is actual content that should be extracted.</p>
    <div>
        <p>First paragraph with meaningful text.</p>
        <p>Second paragraph with more content.</p>
    </div>
</body>
</html>'''

        text1 = html_to_text(html1)

        # Before fix: would return ~33 newlines, len(text) ~= 33
        # After fix: should extract actual content, len(text) > 100
        assert len(text1) > 100, f"Expected substantial text output, got {len(text1)} chars"
        assert 'Important Heading' in text1, "Failed to extract heading from display:none body"
        assert 'actual content' in text1, "Failed to extract paragraph from display:none body"
        assert 'First paragraph' in text1, "Failed to extract nested content"

        # Should not be mostly newlines
        newline_ratio = text1.count('\n') / len(text1)
        assert newline_ratio < 0.5, f"Output is mostly newlines ({newline_ratio:.2%}), content not extracted"

        # Test case 2: visibility:hidden (another hiding pattern)
        html2 = '<html><body style="visibility:hidden"><h1>Hidden Content</h1><p>Test paragraph.</p></body></html>'
        text2 = html_to_text(html2)

        assert 'Hidden Content' in text2, "Failed to extract content from visibility:hidden body"
        assert 'Test paragraph' in text2, "Failed to extract paragraph from visibility:hidden body"

        # Test case 3: Mixed styles (display:none with other CSS)
        html3 = '<html><body style="color: red; display:none; font-size: 12px"><p>Mixed style content</p></body></html>'
        text3 = html_to_text(html3)

        assert 'Mixed style content' in text3, "Failed to extract content from body with mixed styles"

        # Test case 4: Case insensitivity (DISPLAY:NONE uppercase)
        html4 = '<html><body style="DISPLAY:NONE"><p>Uppercase style</p></body></html>'
        text4 = html_to_text(html4)

        assert 'Uppercase style' in text4, "Failed to handle uppercase DISPLAY:NONE"

        # Test case 5: Space variations (display: none vs display:none)
        html5 = '<html><body style="display: none"><p>With spaces</p></body></html>'
        text5 = html_to_text(html5)

        assert 'With spaces' in text5, "Failed to handle 'display: none' with space"

        # Test case 6: Body with other attributes (class, id)
        html6 = '<html><body class="foo" style="display:none" id="bar"><p>With attributes</p></body></html>'
        text6 = html_to_text(html6)

        assert 'With attributes' in text6, "Failed to extract from body with multiple attributes"

        # Test case 7: Should NOT affect opacity:0 (which doesn't hide from inscriptis)
        html7 = '<html><body style="opacity:0"><p>Transparent content</p></body></html>'
        text7 = html_to_text(html7)

        # Opacity doesn't affect inscriptis text extraction, content should be there
        assert 'Transparent content' in text7, "Incorrectly stripped opacity:0 style"

        print("  ✓ All display:none body tag tests passed")

    def test_style_tag_with_svg_data_uri(self):
        """
        Test that style tags containing SVG data URIs are properly stripped.

        Some WordPress and modern sites embed SVG as data URIs in CSS, which contains
        <svg> and </svg> tags within the style content. The regex must use backreferences
        to ensure <style> matches </style> (not </svg> inside the CSS).

        This was causing errors where the regex would match <style> and stop at the first
        </svg> it encountered inside a CSS data URI, breaking the HTML structure.
        """
        # Real-world example from WordPress wp-block-image styles
        html = '''<!DOCTYPE html>
<html>
<head>
    <style id='wp-block-image-inline-css'>
.wp-block-image>a,.wp-block-image>figure>a{display:inline-block}.wp-block-image img{box-sizing:border-box;height:auto;max-width:100%;vertical-align:bottom}@supports ((-webkit-mask-image:none) or (mask-image:none)) or (-webkit-mask-image:none){.wp-block-image.is-style-circle-mask img{border-radius:0;-webkit-mask-image:url('data:image/svg+xml;utf8,<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="50"/></svg>');mask-image:url('data:image/svg+xml;utf8,<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><circle cx="50" cy="50" r="50"/></svg>');mask-mode:alpha}}
    </style>
</head>
<body>
    <h1>Test Heading</h1>
    <p>This is the actual content that should be extracted.</p>
    <div class="wp-block-image">
        <img src="test.jpg" alt="Test image">
    </div>
</body>
</html>'''

        # This should not crash and should extract the body content
        text = html_to_text(html)

        # Verify the actual body content was extracted
        assert text is not None, "html_to_text returned None"
        assert len(text) > 0, "html_to_text returned empty string"
        assert 'Test Heading' in text, "Failed to extract heading"
        assert 'actual content that should be extracted' in text, "Failed to extract paragraph"

        # Verify CSS content was stripped (including the SVG data URI)
        assert '.wp-block-image' not in text, "CSS class selector leaked into text"
        assert 'mask-image' not in text, "CSS property leaked into text"
        assert 'data:image/svg+xml' not in text, "SVG data URI leaked into text"
        assert 'viewBox' not in text, "SVG attributes leaked into text"

        # Verify no broken HTML structure
        assert '<style' not in text, "Unclosed style tag in output"
        assert '</svg>' not in text, "SVG closing tag leaked into text"

        print("  ✓ Style tag with SVG data URI test passed")

    def test_style_tag_closes_correctly(self):
        """
        Test that each tag type (style, script, svg) closes with the correct closing tag.

        Before the fix, the regex used (?:style|script|svg|noscript) for both opening and
        closing tags, which meant <style> could incorrectly match </svg> as its closing tag.
        With backreferences, <style> must close with </style>, <svg> with </svg>, etc.
        """
        # Test nested tags where incorrect matching would break
        html = '''<!DOCTYPE html>
<html>
<head>
    <style>
        body { background: url('data:image/svg+xml,<svg><rect/></svg>'); }
    </style>
    <script>
        const svg = '<svg><path d="M0,0"/></svg>';
    </script>
</head>
<body>
    <h1>Content</h1>
    <svg><circle cx="50" cy="50" r="40"/></svg>
    <p>After SVG</p>
</body>
</html>'''

        text = html_to_text(html)

        # Should extract body content
        assert 'Content' in text, "Failed to extract heading"
        assert 'After SVG' in text, "Failed to extract content after SVG"

        # Should strip all style/script/svg content
        assert 'background:' not in text, "Style content leaked"
        assert 'const svg' not in text, "Script content leaked"
        assert '<circle' not in text, "SVG element leaked"
        assert 'data:image/svg+xml' not in text, "Data URI leaked"

        print("  ✓ Tag closing validation test passed")



    def test_script_with_closing_tag_in_string_does_not_eat_content(self):
        """
        Script tag containing </script> inside a JS string must not prematurely end the block.

        This is the classic regex failure mode: the old pattern would find the first </script>
        inside the JS string literal and stop there, leaving the tail of the script block
        (plus any following content) exposed as raw text. BS4 parses the HTML correctly.
        """
        html = '''<html><body>
<p>Before script</p>
<script>
var html = "<div>foo<\\/script><p>bar</p>";
var also = 1;
</script>
<p>AFTER SCRIPT</p>
</body></html>'''

        text = html_to_text(html)
        assert 'Before script' in text
        assert 'AFTER SCRIPT' in text
        # Script internals must not leak
        assert 'var html' not in text
        assert 'var also' not in text

    def test_content_sandwiched_between_multiple_body_scripts(self):
        """Content between multiple script/style blocks in the body must all survive."""
        html = '''<html><body>
<script>var a = 1;</script>
<p>CONTENT A</p>
<style>.x { color: red; }</style>
<p>CONTENT B</p>
<script>var b = 2;</script>
<p>CONTENT C</p>
<style>.y { color: blue; }</style>
<p>CONTENT D</p>
</body></html>'''

        text = html_to_text(html)
        for label in ['CONTENT A', 'CONTENT B', 'CONTENT C', 'CONTENT D']:
            assert label in text, f"'{label}' was eaten by script/style stripping"
        assert 'var a' not in text
        assert 'var b' not in text
        assert 'color: red' not in text
        assert 'color: blue' not in text

    def test_unicode_and_international_content_preserved(self):
        """Non-ASCII content (umlauts, CJK, soft hyphens) must survive stripping."""
        html = '''<html><body>
<style>.x{color:red}</style>
<p>German: Aus\xadge\xadbucht! — ANMELDUNG — Fan\xadday 2026</p>
<p>Chinese: \u6ce8\u518c</p>
<p>Japanese: \u767b\u9332</p>
<p>Korean: \ub4f1\ub85d</p>
<p>Emoji: \U0001f4e2</p>
<script>var x = 1;</script>
</body></html>'''

        text = html_to_text(html)
        assert 'ANMELDUNG' in text
        assert '\u6ce8\u518c' in text   # Chinese
        assert '\u767b\u9332' in text   # Japanese
        assert '\ub4f1\ub85d' in text   # Korean

    def test_style_with_type_attribute_is_stripped(self):
        """<style type="text/css"> (with type attribute) must be stripped just like bare <style>."""
        html = '''<html><body>
<style type="text/css">.important { display: none; }</style>
<p>VISIBLE CONTENT</p>
</body></html>'''

        text = html_to_text(html)
        assert 'VISIBLE CONTENT' in text
        assert '.important' not in text
        assert 'display: none' not in text

    def test_ldjson_script_is_stripped(self):
        """<script type="application/ld+json"> must be stripped — raw JSON must not appear as text."""
        html = '''<html><body>
<script type="application/ld+json">
{"@type": "Product", "name": "Widget", "price": "9.99"}
</script>
<p>PRODUCT PAGE</p>
</body></html>'''

        text = html_to_text(html)
        assert 'PRODUCT PAGE' in text
        assert '@type' not in text
        assert '"price"' not in text

    def test_inline_svg_path_data_does_not_appear_in_text(self):
        """
        Inline SVG elements in the body are not stripped by BS4, but inscriptis must not
        render their path data (d="M0,0 L100,100") as visible text.
        """
        html = '''<html><body>
<p>Before SVG</p>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
    <path d="M14 5L7 12L14 19Z" fill="none"/>
    <circle cx="12" cy="12" r="10"/>
</svg>
<p>After SVG</p>
</body></html>'''

        text = html_to_text(html)
        assert 'Before SVG' in text
        assert 'After SVG' in text
        assert 'M14 5L7' not in text, "SVG path data should not appear in text output"

    def test_tag_inside_json_data_attribute_does_not_eat_content(self):
        """
        Tags inside JSON data attributes with JS-escaped closing tags must not eat real content.

        Real-world case: Elementor/JetEngine WordPress widgets embed HTML (including SVG icons)
        inside JSON data attributes like data-slider-atts. The HTML inside is JS-escaped, so
        closing tags appear as <\\/svg> rather than </svg>.

        The old regex approach would find <svg> inside the attribute value, then fail to find
        <\/svg> as a matching close tag, and scan forward to the next real </svg> in the DOM —
        eating tens of kilobytes of actual page content in the process.
        """
        html = '''<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<div class="slider" data-slider-atts="{&quot;prevArrow&quot;:&quot;<i class=\\&quot;icon\\&quot;><svg width=\\&quot;24\\&quot; height=\\&quot;24\\&quot; viewBox=\\&quot;0 0 24 24\\&quot; xmlns=\\&quot;http:\\/\\/www.w3.org\\/2000\\/svg\\&quot;><path d=\\&quot;M14 5L7 12L14 19\\&quot;\\/><\\/svg><\\/i>&quot;}">
</div>
<div class="content">
    <h1>IMPORTANT CONTENT</h1>
    <p>This text must not be eaten by the tag-stripping logic.</p>
</div>
<svg><circle cx="50" cy="50" r="40"/></svg>
</body>
</html>'''

        text = html_to_text(html)

        assert 'IMPORTANT CONTENT' in text, (
            "Content after a JS-escaped tag in a data attribute was incorrectly stripped. "
            "The tag-stripping logic is matching <tag> inside attribute values and scanning "
            "forward to the next real closing tag in the DOM."
        )
        assert 'This text must not be eaten' in text

    def test_script_inside_json_data_attribute_does_not_eat_content(self):
        """Same issue as above but with <script> embedded in a data attribute with JS-escaped closing tag."""
        html = '''<!DOCTYPE html>
<html>
<head><title>Test</title></head>
<body>
<div data-config="{&quot;template&quot;:&quot;<script type=\\&quot;text\\/javascript\\&quot;>var x=1;<\\/script>&quot;}">
</div>
<div>
    <h1>MUST SURVIVE</h1>
    <p>Real content after the data attribute with embedded script tag.</p>
</div>
<script>var real = 1;</script>
</body>
</html>'''

        text = html_to_text(html)

        assert 'MUST SURVIVE' in text, (
            "Content after a JS-escaped <script> in a data attribute was incorrectly stripped."
        )
        assert 'Real content after the data attribute' in text


if __name__ == '__main__':
    # Can run this file directly for quick testing
    unittest.main()
