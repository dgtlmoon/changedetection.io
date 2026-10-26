#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_jinja2_security

import unittest
import pytest
from changedetectionio import jinja2_custom as safe_jinja


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


@pytest.mark.parametrize("text", [
    'https://example.com/{{watch_url}}',
    'https://example.com/{% if foo %}bar{% endif %}',
    "https://example.com/{% now 'Europe/Berlin', '%Y' %}",
    '{%- if foo -%}',
    '{%+ if foo +%}',
])
def test_jinja2_marker_pattern_true_positives(text):
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN
    assert JINJA2_MARKER_PATTERN.search(text)


@pytest.mark.parametrize("text", [
    '',
    'https://example.com/api?q={%22key%22:1}',
])
def test_jinja2_marker_pattern_false_positives(text):
    from changedetectionio.jinja2_custom import JINJA2_MARKER_PATTERN
    assert not JINJA2_MARKER_PATTERN.search(text)



if __name__ == '__main__':
    unittest.main()
