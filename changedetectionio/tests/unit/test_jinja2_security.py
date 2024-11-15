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



if __name__ == '__main__':
    unittest.main()
