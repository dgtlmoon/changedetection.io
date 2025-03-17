import pytest
from unittest.mock import MagicMock, patch
from changedetectionio.processors.whois_plugin import WhoisProcessor


class MockWatch:
    def __init__(self, url, previous_md5=None, include_filters=None, ignore_text=None):
        self.url = url
        self._previous_md5 = previous_md5
        self._include_filters = include_filters or []
        self._ignore_text = ignore_text or []
        self.history = {}
    
    def get(self, key, default=None):
        if key == 'previous_md5':
            return self._previous_md5
        elif key == 'include_filters':
            return self._include_filters
        elif key == 'ignore_text':
            return self._ignore_text
        elif key == 'url':
            return self.url
        return default
    
    def has_special_diff_filter_options_set(self):
        return False


@patch('whois.whois')
@patch('changedetectionio.processors.difference_detection_processor.__init__')
@patch('changedetectionio.processors.text_json_diff.processor.perform_site_check.run_changedetection')
def test_whois_processor_basic_functionality(mock_super_run, mock_base_init, mock_whois):
    """Test the basic functionality of the WhoisProcessor"""
    # Mock the base class init so we don't need to set up the full watch structure
    mock_base_init.return_value = None
    
    # Mock super().run_changedetection to return a simple result
    mock_super_run.return_value = (False, {'previous_md5': 'some-md5'}, b'Some filtered text')
    
    # Mock the whois response
    mock_whois_result = MagicMock()
    mock_whois_result.text = "Domain Name: example.com\nRegistrar: Example Registrar\nCreation Date: 2020-01-01\n"
    mock_whois.return_value = mock_whois_result
    
    # Create mock datastore
    mock_datastore = MagicMock()
    mock_datastore.proxy_list = None  # No proxies
    mock_datastore.get_preferred_proxy_for_watch.return_value = None
    mock_datastore.data = {
        'settings': {
            'application': {
                'allow_file_uri': False
            }
        }
    }
    
    # Create a processor instance and setup minimal required attributes
    processor = WhoisProcessor(datastore=mock_datastore, watch_uuid='test-uuid')
    
    # Create a minimal watch object
    watch = MockWatch(url="https://example.com")
    
    # Simulate link access in the watch
    processor.watch = MagicMock()
    processor.watch.link = "https://example.com"
    processor.watch.get.return_value = "uuid-123"
    
    # Run the processor's run_changedetection method by first using call_browser
    processor.call_browser()
    
    # Check that the fetcher was set up correctly
    assert processor.fetcher is not None
    assert hasattr(processor.fetcher, 'content')
    assert hasattr(processor.fetcher, 'headers')
    assert hasattr(processor.fetcher, 'status_code')
    
    # Verify that whois was called with the right domain
    assert mock_whois.called
    assert mock_whois.call_args[0][0] == 'example.com'
    
    # Now run the processor
    result = processor.run_changedetection(watch)
    
    # Check that the parent run_changedetection was called
    assert mock_super_run.called


@patch('whois.whois')
@patch('changedetectionio.processors.difference_detection_processor.__init__')
def test_whois_processor_call_browser_with_proxy(mock_base_init, mock_whois):
    """Test the call_browser method with proxy configuration"""
    # Mock the base class init
    mock_base_init.return_value = None
    
    # Mock the whois response
    mock_whois_result = MagicMock()
    mock_whois_result.text = "Domain Name: example.com\nRegistrar: Example Registrar\nCreation Date: 2020-01-01\n"
    mock_whois.return_value = mock_whois_result
    
    # Create mock datastore
    mock_datastore = MagicMock()
    mock_proxy = {
        'test-proxy': {
            'url': 'http://proxy.example.com:8080',
            'label': 'Test Proxy'
        }
    }
    mock_datastore.proxy_list = mock_proxy
    mock_datastore.get_preferred_proxy_for_watch.return_value = 'test-proxy'
    mock_datastore.data = {
        'settings': {
            'application': {
                'allow_file_uri': False
            }
        }
    }
    
    # Create a processor instance with our mock datastore
    processor = WhoisProcessor(datastore=mock_datastore, watch_uuid='test-uuid')
    
    # Set up watch
    processor.watch = MagicMock()
    processor.watch.link = "https://example.com"
    processor.watch.get.return_value = "uuid-123"
    
    # Call the method with a proxy
    processor.call_browser()
    
    # Verify whois was called
    assert mock_whois.called
    assert mock_whois.call_args[0][0] == 'example.com'
    
    # Check that the fetcher was set up correctly
    assert processor.fetcher is not None
    assert processor.fetcher.content is not None


@patch('changedetectionio.processors.difference_detection_processor.__init__')
def test_whois_processor_perform_site_check(mock_base_init):
    """Test the WhoisProcessor.perform_site_check static method"""
    mock_base_init.return_value = None
    
    # Test the static method
    with patch.object(WhoisProcessor, '__init__', return_value=None) as mock_init:
        datastore = MagicMock()
        watch_uuid = "test-uuid"
        
        # Call the static method
        processor = WhoisProcessor.perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
        
        # Check that constructor was called with expected args
        mock_init.assert_called_once_with(datastore=datastore, watch_uuid=watch_uuid)
        
        # Check it returns the right type
        assert isinstance(processor, WhoisProcessor)


def test_get_display_link():
    """Test the get_display_link hook implementation"""
    from changedetectionio.processors.whois_plugin import get_display_link
    
    # Test with a regular URL
    url = "https://example.com/some/path?param=value"
    processor_name = "whois"
    link = get_display_link(url=url, processor_name=processor_name)
    assert link == "WHOIS - example.com"
    
    # Test with a subdomain
    url = "https://subdomain.example.com/"
    link = get_display_link(url=url, processor_name=processor_name)
    assert link == "WHOIS - subdomain.example.com"
    
    # Test with www prefix (should be removed)
    url = "https://www.example.com/"
    link = get_display_link(url=url, processor_name=processor_name)
    assert link == "WHOIS - example.com"
    
    # Test with a different processor (should return None)
    url = "https://example.com/"
    processor_name = "text_json_diff"
    link = get_display_link(url=url, processor_name=processor_name)
    assert link is None