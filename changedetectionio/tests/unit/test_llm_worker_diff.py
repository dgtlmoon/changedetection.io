#!/usr/bin/env python3

import unittest
from difflib import unified_diff
from unittest.mock import MagicMock
from changedetectionio.llm.evaluator import evaluate_change, summarise_change


class TestLLMWorkerDiffHandling(unittest.TestCase):
    def test_empty_diff_returns_none_and_does_not_clear_changed_detected(self):
        """
        When consecutive snapshots have zero diff lines (e.g. image SSIM, restock
        metadata, or filtered changes), evaluate_change must return None (not
        important=False) so changed_detected is not suppressed.
        """
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

        # 1. evaluate_change must return None on empty diff (on master this returned {'important': False, ...})
        eval_res = evaluate_change(watch, mock_ds, diff=diff_text)
        self.assertIsNone(eval_res)

        # 2. Worker logic: empty diff must NOT suppress changed_detected
        changed_detected = True
        if eval_res and not eval_res.get('important', True):
            changed_detected = False
        self.assertTrue(changed_detected, "Empty diff must not clear changed_detected")

        # 3. summarise_change must return empty string on empty diff
        summary_res = summarise_change(watch, mock_ds, diff=diff_text)
        self.assertEqual(summary_res, '')


if __name__ == '__main__':
    unittest.main()
