#!/usr/bin/env python3

from changedetectionio.processors import available_processors
from changedetectionio.processors.processor_registry import get_processor_class
import unittest
import sys
from unittest.mock import MagicMock, patch
import urllib.parse

# First, verify our processor is available
print("=== Available Processors ===")
processors = available_processors()
for name, description in processors:
    print(f"Processor: {name} - {description}")

# Get the WHOIS processor class
whois_processor_class = get_processor_class("whois_processor")
if not whois_processor_class:
    print("ERROR: WHOIS processor not found in available processors.")
    sys.exit(1)

print(f"\nFound WHOIS processor class: {whois_processor_class}")

# Create a test for our WHOIS processor
class TestWhoisProcessor(unittest.TestCase):
    
    # Use the real whois function - tests will actually make network requests
    def test_whois_processor_real(self):
        # Extract the domain from the URL
        test_url = "https://changedetection.io"
        parsed_url = urllib.parse.urlparse(test_url)
        domain = parsed_url.netloc
        
        # Create a minimal mock datastore
        mock_datastore = MagicMock()
        mock_datastore.data = {
            'watching': {'test-uuid': {'url': test_url}},
            'settings': {
                'application': {'empty_pages_are_a_change': False},
                'requests': {'timeout': 30}
            }
        }
        mock_datastore.get_all_base_headers.return_value = {}
        mock_datastore.get_all_headers_in_textfile_for_watch.return_value = {}
        mock_datastore.get_preferred_proxy_for_watch.return_value = None
        mock_datastore.get_tag_overrides_for_watch.return_value = []
        
        # Create a minimal mock watch that mimics the real Watch class
        class MockWatch:
            def __init__(self, url):
                self.link = url
                self.is_pdf = False
                self.has_browser_steps = False
                self.is_source_type_url = False
                self.history = {}
                self.history_n = 0
                self.last_viewed = 0
                self.newest_history_key = 0
                
            def get(self, key, default=None):
                if key == 'uuid':
                    return 'test-uuid'
                elif key == 'include_filters':
                    return []
                elif key == 'body':
                    return None
                elif key == 'method':
                    return 'GET'
                elif key == 'headers':
                    return {}
                elif key == 'browser_steps':
                    return []
                return default
                
            def __getitem__(self, key):
                return self.get(key)
                
            def get_last_fetched_text_before_filters(self):
                return ""
            
            def save_last_text_fetched_before_filters(self, content):
                pass
                
            def has_special_diff_filter_options_set(self):
                return False
                
            def lines_contain_something_unique_compared_to_history(self, lines, ignore_whitespace):
                return True
                
        mock_watch = MockWatch(test_url)
        
        # Create a more complete mock fetcher
        class MockFetcher:
            def __init__(self):
                self.content = ""
                self.raw_content = b""
                self.headers = {'Content-Type': 'text/plain'}
                self.screenshot = None
                self.xpath_data = None
                self.instock_data = None
                self.browser_steps = []
            
            def get_last_status_code(self):
                return 200
                
            def get_all_headers(self):
                return {'content-type': 'text/plain'}
                
            def quit(self):
                pass
                
            def run(self, **kwargs):
                pass
                
        # Create the processor and set the mock fetcher
        processor = whois_processor_class(datastore=mock_datastore, watch_uuid='test-uuid')
        processor.fetcher = MockFetcher()
        
        # Run the processor - this will make an actual WHOIS request
        changed, update_obj, content = processor.run_changedetection(mock_watch)
        
        # Print the content for debugging
        content_str = content.decode('utf-8')
        print(f"\n=== WHOIS Content from processor (first 200 chars) ===")
        print(content_str[:200] + "...")
        
        # Verify the content contains domain information
        self.assertIn(domain, content_str)
        self.assertIn("Domain Name", content_str)
        self.assertIn("Creation Date", content_str)
        
        print("\nWHOIS processor test with real data PASSED!")

# Run the test
if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)