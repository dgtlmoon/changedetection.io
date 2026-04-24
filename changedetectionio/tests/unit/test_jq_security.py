#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_jq_security

import unittest


class TestJqExpressionSecurity(unittest.TestCase):

    def test_blocked_builtins_raise(self):
        """Each dangerous builtin must be rejected by validate_jq_expression."""
        from changedetectionio.html_tools import validate_jq_expression

        blocked = [
            # env access
            'env',
            '.foo | env',
            '$ENV',
            '$ENV.SECRET',
            # file read via module system
            'include "foo"',
            'import "foo" as f',
            # stdin reads
            'input',
            'inputs',
            '[.,inputs]',
            # process termination
            'halt',
            'halt_error(1)',
            # stderr/debug leakage
            'debug',
            '. | debug | .foo',
            'stderr',
            # misc info leakage
            '$__loc__',
            'builtins',
            'modulemeta',
            '$JQ_BUILD_CONFIGURATION',
        ]

        for expr in blocked:
            with self.assertRaises(ValueError, msg=f"Expected ValueError for: {expr!r}"):
                validate_jq_expression(expr)

    def test_safe_expressions_pass(self):
        """Normal jq expressions must not be blocked."""
        from changedetectionio.html_tools import validate_jq_expression

        safe = [
            '.foo',
            '.items[] | .price',
            'map(select(.active)) | length',
            '.[] | select(.name | test("foo"))',
            'to_entries | map(.value) | add',
            '[.[] | .id] | unique',
            '.price | tonumber',
            'if .stock > 0 then "in stock" else "out of stock" end',
        ]

        for expr in safe:
            try:
                validate_jq_expression(expr)
            except ValueError as e:
                self.fail(f"validate_jq_expression raised ValueError for safe expression {expr!r}: {e}")

    def test_allow_risky_env_var_bypasses_check(self):
        """JQ_ALLOW_RISKY_EXPRESSIONS=true must skip all blocking."""
        import os
        from unittest.mock import patch
        from changedetectionio.html_tools import validate_jq_expression

        with patch.dict(os.environ, {'JQ_ALLOW_RISKY_EXPRESSIONS': 'true'}):
            # Should not raise even for the most dangerous expression
            try:
                validate_jq_expression('env')
                validate_jq_expression('$ENV')
            except ValueError as e:
                self.fail(f"Should not block when JQ_ALLOW_RISKY_EXPRESSIONS=true: {e}")

    def test_allow_risky_env_var_off_by_default(self):
        """Without JQ_ALLOW_RISKY_EXPRESSIONS set, blocking must be active."""
        import os
        from unittest.mock import patch
        from changedetectionio.html_tools import validate_jq_expression

        env = {k: v for k, v in os.environ.items() if k != 'JQ_ALLOW_RISKY_EXPRESSIONS'}
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ValueError):
                validate_jq_expression('env')


if __name__ == '__main__':
    unittest.main()
