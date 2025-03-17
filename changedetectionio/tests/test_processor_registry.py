import pytest
from changedetectionio.processors.processor_registry import get_processor_class, get_all_processors


def test_get_all_processors():
    """Test that get_all_processors returns a list of processor tuples"""
    processors = get_all_processors()
    assert isinstance(processors, list)
    assert len(processors) > 0
    
    # Each item should be a tuple of (name, description)
    for processor in processors:
        assert isinstance(processor, tuple)
        assert len(processor) == 2
        assert isinstance(processor[0], str)
        assert isinstance(processor[1], str)
        
    # Check that our WHOIS processor is included
    whois_processor = next((p for p in processors if p[0] == "whois"), None)
    assert whois_processor is not None
    assert whois_processor[1] == "WHOIS Domain Information Changes"


def test_get_processor_class():
    """Test that get_processor_class returns the right class"""
    # Get the WHOIS processor class
    processor_class = get_processor_class("whois")
    assert processor_class is not None
    
    # It should have perform_site_check method
    assert hasattr(processor_class, 'perform_site_check')
    
    # Check for non-existent processor
    non_existent = get_processor_class("non_existent_processor")
    assert non_existent is None


def test_get_processor_site_check():
    """Test that get_processor_site_check returns a processor instance"""
    from unittest.mock import MagicMock
    from changedetectionio.processors.processor_registry import get_processor_site_check
    
    # Get a WHOIS processor instance
    mock_datastore = MagicMock()
    watch_uuid = "test-uuid"
    processor = get_processor_site_check("whois", mock_datastore, watch_uuid)
    
    # It should be a processor instance
    assert processor is not None
    
    # It should have the run_changedetection method
    assert hasattr(processor, 'run_changedetection')
    
    # It should have the call_browser method
    assert hasattr(processor, 'call_browser')
    
    # Check for non-existent processor
    non_existent = get_processor_site_check("non_existent_processor", mock_datastore, watch_uuid)
    assert non_existent is None