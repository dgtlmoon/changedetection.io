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


if __name__ == '__main__':
    # Can run this file directly for quick testing
    unittest.main()
