#!/usr/bin/env python3

import tempfile
import unittest

from changedetectionio.api import (
    get_tag_schema_properties,
    get_watch_schema_properties,
    strip_internal_api_fields,
)
from changedetectionio.model import Watch
from changedetectionio.model.schema_utils import (
    SYSTEM_MANAGED_NON_SPEC_FIELDS,
    get_readonly_watch_fields,
)


class TestSchemaUtils(unittest.TestCase):
    """
    Tests for schema separation and internal/spec field boundaries.

    Ensures that SYSTEM_MANAGED_NON_SPEC_FIELDS only contains internal runtime
    fields not present in the OpenAPI spec, and that OpenAPI readOnly fields
    are properly handled without breaking the watch.was_edited flag or API responses.
    """

    def test_schema_separation_invariant(self):
        """
        SYSTEM_MANAGED_NON_SPEC_FIELDS must strictly be disjoint from the OpenAPI spec.

        Fields in the OpenAPI spec marked as `readOnly: true` (e.g. LLM token counters
        and cache properties) are handled by get_readonly_watch_fields() and must NOT
        be placed in SYSTEM_MANAGED_NON_SPEC_FIELDS (which would strip them from GET).
        """
        readonly_watch_fields = get_readonly_watch_fields()
        watch_schema_props = set(get_watch_schema_properties().keys())
        tag_schema_props = set(get_tag_schema_properties().keys())

        # No system-managed non-spec field should overlap with OpenAPI readonly fields
        overlap_readonly = SYSTEM_MANAGED_NON_SPEC_FIELDS & readonly_watch_fields
        self.assertEqual(
            overlap_readonly,
            set(),
            f"SYSTEM_MANAGED_NON_SPEC_FIELDS must not contain spec readOnly fields: {overlap_readonly}"
        )

        # No system-managed non-spec field should exist in WatchBase or Tag properties
        overlap_props = SYSTEM_MANAGED_NON_SPEC_FIELDS & (watch_schema_props | tag_schema_props)
        self.assertEqual(
            overlap_props,
            set(),
            f"SYSTEM_MANAGED_NON_SPEC_FIELDS must not contain spec properties: {overlap_props}"
        )

        # Verify truly non-spec fields are present
        expected_non_spec = {
            'last_check_status',
            'last_filter_config_hash',
            'restock',
            '_llm_result',
            '_llm_intent',
            '_llm_change_summary',
        }
        self.assertEqual(SYSTEM_MANAGED_NON_SPEC_FIELDS, expected_non_spec)

        # Verify spec-declared readOnly LLM fields are in get_readonly_watch_fields()
        expected_spec_readonly_llm = {
            'llm_prefilter',
            'llm_evaluation_cache',
            'llm_last_tokens_used',
            'llm_tokens_used_cumulative',
            'llm_tokens_this_period',
            'llm_tokens_period_key',
        }
        for field in expected_spec_readonly_llm:
            self.assertIn(
                field,
                readonly_watch_fields,
                f"Spec field '{field}' must be resolved by get_readonly_watch_fields()"
            )

    def test_watch_was_edited_behavior(self):
        """
        Writing internal or spec-readOnly fields must NOT trip watch.was_edited.

        Only modifying user-writable fields (like 'title' or 'url') should mark
        the watch as edited, ensuring unchanged content checks are not bypassed.
        """
        mock_datastore = {
            'settings': {'application': {}},
            'watching': {}
        }
        watch = Watch.model(
            datastore_path=tempfile.gettempdir(),
            __datastore=mock_datastore,
            default={'url': 'https://example.com', 'title': 'Original'}
        )

        # 1. Non-spec system fields should not trip was_edited
        for field in SYSTEM_MANAGED_NON_SPEC_FIELDS:
            watch.reset_watch_edited_flag()
            watch[field] = 'runtime_internal_value'
            self.assertFalse(
                watch.was_edited,
                f"Writing non-spec field '{field}' must not set was_edited=True"
            )

        # 2. Spec-declared readOnly LLM fields should not trip was_edited
        spec_readonly_llm_fields = [
            'llm_prefilter',
            'llm_evaluation_cache',
            'llm_last_tokens_used',
            'llm_tokens_used_cumulative',
            'llm_tokens_this_period',
            'llm_tokens_period_key',
        ]
        for field in spec_readonly_llm_fields:
            watch.reset_watch_edited_flag()
            watch[field] = 1234
            self.assertFalse(
                watch.was_edited,
                f"Writing spec readOnly field '{field}' must not set was_edited=True"
            )

        # 3. Writable fields MUST trip was_edited
        watch.reset_watch_edited_flag()
        watch['title'] = 'Updated Title'
        self.assertTrue(
            watch.was_edited,
            "Modifying writable field 'title' must set was_edited=True"
        )

        watch.reset_watch_edited_flag()
        watch['url'] = 'https://example.org/new'
        self.assertTrue(
            watch.was_edited,
            "Modifying writable field 'url' must set was_edited=True"
        )

    def test_strip_internal_api_fields_preserves_spec_fields(self):
        """
        strip_internal_api_fields() must strip internal fields but preserve spec fields.

        Consumers querying GET /api/v1/watch/<uuid> need access to spec-documented
        LLM token usage counters and evaluation caches, while runtime internals
        like _llm_result or skip-cache hashes must be stripped.
        """
        data = {
            'url': 'https://example.com',
            'title': 'Test Page',
            '__check_status': 'Checking...',
            'last_check_status': 200,
            'last_filter_config_hash': 'hash_123',
            'restock': {'in_stock': True},
            '_llm_result': {'important': True},
            '_llm_intent': 'watch for price drops',
            '_llm_change_summary': 'Price dropped',
            'llm_prefilter': '#price',
            'llm_evaluation_cache': {'hash_abc': {'result': True}},
            'llm_last_tokens_used': 150,
            'llm_tokens_used_cumulative': 1500,
            'llm_tokens_this_period': 450,
            'llm_tokens_period_key': '2026-09',
        }

        stripped = strip_internal_api_fields(data)

        # Truly internal runtime fields must be stripped
        for field in SYSTEM_MANAGED_NON_SPEC_FIELDS:
            self.assertNotIn(field, stripped, f"Internal field '{field}' must be stripped from API")
        self.assertNotIn('__check_status', stripped, "__-prefixed field must be stripped from API")

        # Spec fields (both writable and readOnly) must be preserved in GET responses
        expected_preserved = {
            'url': 'https://example.com',
            'title': 'Test Page',
            'llm_prefilter': '#price',
            'llm_evaluation_cache': {'hash_abc': {'result': True}},
            'llm_last_tokens_used': 150,
            'llm_tokens_used_cumulative': 1500,
            'llm_tokens_this_period': 450,
            'llm_tokens_period_key': '2026-09',
        }
        for key, val in expected_preserved.items():
            self.assertIn(key, stripped, f"Spec field '{key}' must be preserved by strip_internal_api_fields")
            self.assertEqual(stripped[key], val)

    def test_put_roundtrip_readonly_handling(self):
        """
        When a client round-trips a GET response to PUT, readOnly fields must be ignored.

        Simulates api/Watch.py: popping get_readonly_watch_fields() ensures valid_fields
        validation succeeds without unknown-field errors.
        """
        readonly_fields = get_readonly_watch_fields()
        valid_fields = set(get_watch_schema_properties().keys())

        # Payload simulating a full GET response being sent back via PUT
        payload = {
            'url': 'https://example.com',
            'title': 'Test Page',
            'uuid': '095be615-a8ad-4c33-8e9c-c7612fbf6c9f',
            'date_created': 1700000000,
            'llm_prefilter': '#price',
            'llm_evaluation_cache': {'hash_abc': {'result': True}},
            'llm_last_tokens_used': 150,
            'llm_tokens_used_cumulative': 1500,
            'llm_tokens_this_period': 450,
            'llm_tokens_period_key': '2026-09',
        }

        # Simulate PUT handler behavior in api/Watch.py:241-268
        for field in readonly_fields:
            payload.pop(field, None)

        unknown_fields = set(payload.keys()) - valid_fields
        self.assertEqual(
            unknown_fields,
            set(),
            f"No unknown fields should remain after popping readOnly fields: {unknown_fields}"
        )
        self.assertEqual(payload, {'url': 'https://example.com', 'title': 'Test Page'})


if __name__ == '__main__':
    unittest.main()
