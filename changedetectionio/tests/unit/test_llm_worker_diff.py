#!/usr/bin/env python3

import unittest
from difflib import unified_diff
from unittest.mock import MagicMock
from changedetectionio.llm.evaluator import evaluate_change, summarise_change


class TestLLMWorkerDiffHandling(unittest.TestCase):
    def test_empty_diff_does_not_call_llm_and_returns_defaults(self):
        """When unified diff has zero lines, LLM calls should not occur and default safe results returned."""
        prev_text = "<html><body><h1>Hello World</h1></body></html>"
        contents = "<html><body><h1>Hello World</h1></body></html>"

        diff_lines = list(unified_diff(
            prev_text.splitlines(keepends=True),
            contents.splitlines(keepends=True),
            lineterm='',
            n=3
        ))
        diff_text = ''.join(diff_lines)
        self.assertEqual(diff_text, "")

        mock_ds = MagicMock()
        mock_ds.data = {'settings': {'application': {'llm': {'model': 'gpt-4o-mini', 'api_key': 'fake'}}}}

        watch = {
            'uuid': 'test-uuid',
            'url': 'https://example.com',
            'llm_intent': 'alert if price drops',
            'llm_change_summary': 'describe change',
            'llm_evaluation_cache': {},
            'tags': [],
        }

        # Intent evaluation on empty diff must return important=False without calling LLM
        eval_res = evaluate_change(watch, mock_ds, diff=diff_text)
        self.assertEqual(eval_res, {'important': False, 'summary': ''})

        # Summary on empty diff must return empty string without calling LLM
        summary_res = summarise_change(watch, mock_ds, diff=diff_text)
        self.assertEqual(summary_res, '')


if __name__ == '__main__':
    unittest.main()
