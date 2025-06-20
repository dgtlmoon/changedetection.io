#!/usr/bin/env python3

# run from dir above changedetectionio/ dir
# python3 -m unittest changedetectionio.tests.unit.test_update_watch_deep_merge

import unittest
import os
import tempfile
import shutil
from unittest.mock import patch

from changedetectionio import store


class TestUpdateWatchDeepMerge(unittest.TestCase):

    def setUp(self):
        # Create a temporary directory for test data
        self.test_datastore_path = tempfile.mkdtemp()
        self.datastore = store.ChangeDetectionStore(datastore_path=self.test_datastore_path, include_default_watches=False)
        
        # Create a test watch with known nested structure
        self.test_uuid = self.datastore.add_watch(url='http://example.com')
        
        # Set up known initial nested structure
        initial_data = {
            'time_between_check': {'weeks': None, 'days': 1, 'hours': 6, 'minutes': 30, 'seconds': None},
            'headers': {'user-agent': 'test-browser', 'accept': 'text/html'},
            'time_schedule_limit': {
                'enabled': True,
                'monday': {
                    'enabled': True,
                    'start_time': '09:00',
                    'duration': {'hours': '8', 'minutes': '00'}
                },
                'tuesday': {
                    'enabled': False,
                    'start_time': '10:00',
                    'duration': {'hours': '6', 'minutes': '30'}
                }
            }
        }
        self.datastore.update_watch(self.test_uuid, initial_data)

    def tearDown(self):
        self.datastore.stop_thread = True
        # Clean up the temporary directory
        shutil.rmtree(self.test_datastore_path, ignore_errors=True)

    def test_simple_flat_update(self):
        """Test that simple flat updates work as before"""
        update_obj = {'url': 'http://newexample.com', 'paused': True}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        self.assertEqual(watch['url'], 'http://newexample.com')
        self.assertEqual(watch['paused'], True)

    def test_time_between_check_partial_update(self):
        """Test partial update of time_between_check preserves existing keys"""
        # Update only hours, should preserve other existing values
        update_obj = {'time_between_check': {'hours': 2}}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        time_check = watch['time_between_check']
        
        # Updated value
        self.assertEqual(time_check['hours'], 2)
        # Preserved existing values
        self.assertEqual(time_check['days'], 1)
        self.assertEqual(time_check['minutes'], 30)
        self.assertEqual(time_check['weeks'], None)
        self.assertEqual(time_check['seconds'], None)

    def test_time_between_check_multiple_partial_updates(self):
        """Test multiple partial updates to time_between_check"""
        # First update
        update_obj1 = {'time_between_check': {'minutes': 45}}
        self.datastore.update_watch(self.test_uuid, update_obj1)
        
        # Second update
        update_obj2 = {'time_between_check': {'seconds': 15}}
        self.datastore.update_watch(self.test_uuid, update_obj2)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        time_check = watch['time_between_check']
        
        # Both updates should be preserved
        self.assertEqual(time_check['minutes'], 45)
        self.assertEqual(time_check['seconds'], 15)
        # Original values should be preserved
        self.assertEqual(time_check['days'], 1)
        self.assertEqual(time_check['hours'], 6)

    def test_headers_partial_update(self):
        """Test partial update of headers preserves existing headers"""
        update_obj = {'headers': {'authorization': 'Bearer token123'}}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        headers = watch['headers']
        
        # New header added
        self.assertEqual(headers['authorization'], 'Bearer token123')
        # Existing headers preserved
        self.assertEqual(headers['user-agent'], 'test-browser')
        self.assertEqual(headers['accept'], 'text/html')

    def test_headers_update_existing_key(self):
        """Test updating an existing header key"""
        update_obj = {'headers': {'user-agent': 'new-browser'}}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        headers = watch['headers']
        
        # Updated existing header
        self.assertEqual(headers['user-agent'], 'new-browser')
        # Other headers preserved
        self.assertEqual(headers['accept'], 'text/html')

    def test_time_schedule_limit_deep_nested_update(self):
        """Test deep nested update of time_schedule_limit structure"""
        update_obj = {
            'time_schedule_limit': {
                'monday': {
                    'duration': {'hours': '10'}  # Only update hours, preserve minutes
                }
            }
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        schedule = watch['time_schedule_limit']
        
        # Deep nested update applied
        self.assertEqual(schedule['monday']['duration']['hours'], '10')
        # Existing nested values preserved
        self.assertEqual(schedule['monday']['duration']['minutes'], '00')
        self.assertEqual(schedule['monday']['start_time'], '09:00')
        self.assertEqual(schedule['monday']['enabled'], True)
        # Other days preserved
        self.assertEqual(schedule['tuesday']['enabled'], False)
        self.assertEqual(schedule['enabled'], True)

    def test_mixed_flat_and_nested_update(self):
        """Test update with both flat and nested properties"""
        update_obj = {
            'url': 'http://mixed-update.com',
            'paused': False,
            'time_between_check': {'days': 2, 'minutes': 15},
            'headers': {'cookie': 'session=abc123'}
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        
        # Flat updates
        self.assertEqual(watch['url'], 'http://mixed-update.com')
        self.assertEqual(watch['paused'], False)
        
        # Nested updates
        time_check = watch['time_between_check']
        self.assertEqual(time_check['days'], 2)
        self.assertEqual(time_check['minutes'], 15)
        self.assertEqual(time_check['hours'], 6)  # preserved
        
        headers = watch['headers']
        self.assertEqual(headers['cookie'], 'session=abc123')
        self.assertEqual(headers['user-agent'], 'test-browser')  # preserved

    def test_overwrite_nested_with_flat(self):
        """Test that providing a non-dict value overwrites the entire nested structure"""
        update_obj = {'time_between_check': 'invalid_value'}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        # Should completely replace the nested dict with the string
        self.assertEqual(watch['time_between_check'], 'invalid_value')

    def test_add_new_nested_structure(self):
        """Test adding a completely new nested dictionary"""
        update_obj = {
            'custom_config': {
                'option1': 'value1',
                'nested': {
                    'suboption': 'subvalue'
                }
            }
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        self.assertEqual(watch['custom_config']['option1'], 'value1')
        self.assertEqual(watch['custom_config']['nested']['suboption'], 'subvalue')

    def test_empty_dict_update(self):
        """Test updating with empty dictionaries"""
        update_obj = {'headers': {}}
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        # Empty dict should preserve existing headers (no keys to merge)
        self.assertEqual(watch['headers']['user-agent'], 'test-browser')
        self.assertEqual(watch['headers']['accept'], 'text/html')

    def test_none_values_in_nested_update(self):
        """Test handling None values in nested updates"""
        update_obj = {
            'time_between_check': {
                'hours': None,
                'days': 3
            }
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        time_check = watch['time_between_check']
        
        self.assertEqual(time_check['hours'], None)
        self.assertEqual(time_check['days'], 3)
        self.assertEqual(time_check['minutes'], 30)  # preserved

    def test_real_world_api_update_scenario(self):
        """Test a real-world API update scenario from the codebase analysis"""
        # Based on actual API call patterns found in the codebase
        update_obj = {
            "title": "Updated API Watch",
            'time_between_check': {'minutes': 60},
            'headers': {'authorization': 'Bearer api-token', 'user-agent': 'api-client'},
            'notification_urls': ['https://webhook.example.com']
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        
        # Verify all updates
        self.assertEqual(watch['title'], 'Updated API Watch')
        self.assertEqual(watch['time_between_check']['minutes'], 60)
        self.assertEqual(watch['time_between_check']['days'], 1)  # preserved
        self.assertEqual(watch['headers']['authorization'], 'Bearer api-token')
        self.assertEqual(watch['headers']['user-agent'], 'api-client')  # overwrote existing
        self.assertEqual(watch['headers']['accept'], 'text/html')  # preserved
        self.assertEqual(watch['notification_urls'], ['https://webhook.example.com'])

    def test_watch_not_found(self):
        """Test update_watch with non-existent UUID"""
        # Should not raise an error, just return silently
        fake_uuid = 'non-existent-uuid'
        update_obj = {'url': 'http://should-not-update.com'}
        
        # Should not raise an exception
        self.datastore.update_watch(fake_uuid, update_obj)
        
        # Verify no changes were made to existing watch
        watch = self.datastore.data['watching'][self.test_uuid]
        self.assertNotEqual(watch['url'], 'http://should-not-update.com')

    def test_processor_style_update(self):
        """Test the type of updates made by processors during check operations"""
        # Based on async_update_worker.py patterns
        update_obj = {
            'last_notification_error': False,
            'last_error': False,
            'previous_md5': 'abc123def456',
            'content-type': 'application/json',
            'consecutive_filter_failures': 0,
            'fetch_time': 1.234,
            'check_count': 42
        }
        self.datastore.update_watch(self.test_uuid, update_obj)
        
        watch = self.datastore.data['watching'][self.test_uuid]
        
        # Verify processor updates
        self.assertEqual(watch['last_notification_error'], False)
        self.assertEqual(watch['last_error'], False)
        self.assertEqual(watch['previous_md5'], 'abc123def456')
        self.assertEqual(watch['content-type'], 'application/json')
        self.assertEqual(watch['consecutive_filter_failures'], 0)
        self.assertEqual(watch['fetch_time'], 1.234)
        self.assertEqual(watch['check_count'], 42)
        
        # Verify nested structures weren't affected
        self.assertEqual(watch['time_between_check']['days'], 1)
        self.assertEqual(watch['headers']['user-agent'], 'test-browser')


if __name__ == '__main__':
    unittest.main()