#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_jinja2_security

import unittest
from changedetectionio import safe_jinja


# mostly
class TestJinja2SSTI(unittest.TestCase):

    def test_exception(self):
        import jinja2

        # Where sandbox should kick in
        attempt_list = [
            "My name is {{ self.__init__.__globals__.__builtins__.__import__('os').system('id') }}",
            "{{ self._TemplateReference__context.cycler.__init__.__globals__.os }}",
            "{{ self.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}",
            "{{cycler.__init__.__globals__.os.popen('id').read()}}",
            "{{joiner.__init__.__globals__.os.popen('id').read()}}",
            "{{namespace.__init__.__globals__.os.popen('id').read()}}",
            "{{ ''.__class__.__mro__[2].__subclasses__()[40]('/tmp/hello.txt', 'w').write('Hello here !') }}",
            "My name is {{ self.__init__.__globals__ }}",
            "{{ dict.__base__.__subclasses__() }}"
        ]
        for attempt in attempt_list:
            with self.assertRaises(jinja2.exceptions.SecurityError):
                safe_jinja.render(attempt)

    def test_exception_debug_calls(self):
        import jinja2
        # Where sandbox should kick in - configs and debug calls
        attempt_list = [
            "{% debug %}",
        ]
        for attempt in attempt_list:
            # Usually should be something like 'Encountered unknown tag 'debug'.'
            with self.assertRaises(jinja2.exceptions.TemplateSyntaxError):
                safe_jinja.render(attempt)

    # https://book.hacktricks.xyz/pentesting-web/ssti-server-side-template-injection/jinja2-ssti#accessing-global-objects
    def test_exception_empty_calls(self):
        import jinja2
        attempt_list = [
            "{{config}}",
            "{{ debug }}"
            "{{[].__class__}}",
        ]
        for attempt in attempt_list:
            self.assertEqual(len(safe_jinja.render(attempt)), 0, f"string test '{attempt}' is correctly empty")

    def test_jinja2_escaped_html(self):
        x = safe_jinja.render_fully_escaped('woo <a href="https://google.com">dfdfd</a>')
        self.assertEqual(x, "woo &lt;a href=&#34;https://google.com&#34;&gt;dfdfd&lt;/a&gt;")

    def test_diff_unescape_difference_spans_filter_security(self):
        """Test that diff_unescape_difference_spans filter only allows trusted diff spans and blocks XSS."""
        import re
        from markupsafe import Markup, escape

        # Import the constants from diff module
        from changedetectionio.diff import REMOVED_STYLE, ADDED_STYLE, DIFF_HTML_LABEL_REMOVED, DIFF_HTML_LABEL_ADDED, DIFF_HTML_LABEL_INSERTED

        # Recreate the filter logic for testing
        def diff_unescape_difference_spans(content):
            if not content:
                return Markup('')

            # Step 1: Escape everything like Jinja2 would (XSS protection)
            escaped_content = escape(str(content))

            # Step 2: Selectively unescape only trusted diff spans
            result = re.sub(
                rf'&lt;span style=&#34;({REMOVED_STYLE}|{ADDED_STYLE})&#34; title=&#34;([A-Za-z0-9]+)&#34;&gt;',
                r'<span style="\1" title="\2">',
                str(escaped_content),
                flags=re.IGNORECASE
            )

            # Unescape closing tags (balanced)
            open_count = result.count('<span style=')
            close_count = str(escaped_content).count('&lt;/span&gt;')

            for _ in range(min(open_count, close_count)):
                result = result.replace('&lt;/span&gt;', '</span>', 1)

            return Markup(result)

        # Test 1: Valid diff spans should be unescaped
        valid_diff_content = f'{DIFF_HTML_LABEL_REMOVED.format(content="old text")}\n{DIFF_HTML_LABEL_INSERTED.format(content="new text")}'
        result = diff_unescape_difference_spans(valid_diff_content)
        self.assertIn('<span style=', str(result))  # Should contain unescaped spans
        self.assertIn('old text', str(result))
        self.assertIn('new text', str(result))

        # Test 2: XSS attempts should be blocked
        xss_attempts = [
            '<script>alert("xss")</script>',
            '<span style="background-color: red;" onclick="alert(1)">evil</span>',
            '<span style="background-color: #fadad7; color: #b30000;" title="Removed" onload="alert(1)">text</span>',
            '<img src=x onerror=alert(1)>',
            '"><script>alert(1)</script>'
        ]

        for xss_attempt in xss_attempts:
            result = diff_unescape_difference_spans(xss_attempt)
            # Key security test: Should not contain EXECUTABLE HTML/JS
            # (the critical thing is that < and > are escaped, preventing execution)
            self.assertNotIn('<script>', str(result), f"XSS script tag blocked: {xss_attempt}")
            self.assertNotIn('<img ', str(result), f"XSS img tag blocked: {xss_attempt}")
            # All HTML tags should be escaped
            self.assertIn('&lt;', str(result), f"Content is escaped: {xss_attempt}")
            self.assertIn('&gt;', str(result), f"Content is escaped: {xss_attempt}")
            # The core security principle: no executable HTML should remain
            self.assertFalse(
                any(tag in str(result) for tag in ['<script', '<img', '<iframe', '<object']),
                f"No executable HTML tags present: {xss_attempt}"
            )

        # Test 3: Invalid diff spans should remain escaped
        invalid_diff_spans = [
            '<span style="color: red;" title="Evil">bad</span>',  # Wrong style
            f'<span style="{REMOVED_STYLE}" title="Evil Script">bad</span>',  # Invalid title chars (space not allowed)
            f'<span style="{REMOVED_STYLE}">no title</span>',  # Missing title
        ]

        for invalid_span in invalid_diff_spans:
            result = diff_unescape_difference_spans(invalid_span)
            # Should remain escaped
            self.assertIn('&lt;span', str(result), f"Invalid span remained escaped: {invalid_span}")

        # Test 4: Mixed content - valid diffs + XSS should only unescape valid parts
        mixed_content = f'{DIFF_HTML_LABEL_REMOVED.format(content="safe")}<script>alert(1)</script>'
        result = diff_unescape_difference_spans(mixed_content)
        self.assertIn('<span style=', str(result))  # Valid diff unescaped
        self.assertIn('&lt;script&gt;', str(result))  # XSS remained escaped
        self.assertNotIn('<script>', str(result))  # No actual script tag


if __name__ == '__main__':
    unittest.main()
