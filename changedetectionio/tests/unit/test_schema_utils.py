#!/usr/bin/env python3

import unittest
from changedetectionio.model.schema_utils import SYSTEM_MANAGED_NON_SPEC_FIELDS
from changedetectionio.api import strip_internal_api_fields


class TestSchemaUtils(unittest.TestCase):
    def test_system_managed_non_spec_fields_contains_all_llm_runtime_state(self):
        expected = {
            '_llm_result',
            '_llm_intent',
            '_llm_change_summary',
            'llm_prefilter',
            'llm_evaluation_cache',
            'llm_last_tokens_used',
            'llm_tokens_used_cumulative',
            'llm_tokens_this_period',
            'llm_tokens_period_key',
        }
        for field in expected:
            self.assertIn(field, SYSTEM_MANAGED_NON_SPEC_FIELDS, f"{field} should be in SYSTEM_MANAGED_NON_SPEC_FIELDS")

    def test_strip_internal_api_fields(self):
        data = {
            'url': 'https://example.com',
            'title': 'Test Page',
            '__check_status': 'Checking...',
            'last_check_status': 200,
            '_llm_result': {'important': True},
            '_llm_intent': 'watch for price drops',
            '_llm_change_summary': 'Price dropped by $5',
            'llm_prefilter': '#price',
            'llm_evaluation_cache': {'hash': {}},
            'llm_last_tokens_used': 150,
            'llm_tokens_used_cumulative': 1500,
            'llm_tokens_this_period': 450,
            'llm_tokens_period_key': '2026-09',
        }
        stripped = strip_internal_api_fields(data)
        self.assertEqual(stripped, {'url': 'https://example.com', 'title': 'Test Page'})


if __name__ == '__main__':
    unittest.main()
