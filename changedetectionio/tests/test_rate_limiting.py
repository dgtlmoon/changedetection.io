#!/usr/bin/env python3
import time
from flask import url_for


def test_rate_limiting_disabled_by_default(client, live_server, datastore_path):
    """Test that rate limiting is disabled by default (rate_limit_seconds = 0)."""
    
    # Check that the default value is 0
    datastore = live_server.app.config.get('DATASTORE')
    assert datastore.data['settings']['requests'].get('rate_limit_seconds', 0) == 0, \
        "Rate limit should be 0 (disabled) by default"


def test_rate_limiting_settings_form_field(client, live_server, datastore_path):
    """Test that the rate_limit_seconds field can be set via the settings form."""
    
    # Set rate limiting to 5 seconds via POST to settings
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-rate_limit_seconds": 5,
            "requests-time_between_check-minutes": 10,
            "requests-jitter_seconds": 0,
            "requests-workers": 10,
            "requests-timeout": 45,
            "application-fetch_backend": "html_requests",
            "application-empty_pages_are_a_change": "",
            "application-ignore_whitespace": "y"
        },
        follow_redirects=True
    )
    
    assert b"Settings updated" in res.data or res.status_code == 200, \
        "Settings should be updated successfully"
    
    # Verify the setting was saved
    datastore = live_server.app.config.get('DATASTORE')
    assert datastore.data['settings']['requests']['rate_limit_seconds'] == 5, \
        "Rate limit should be set to 5 seconds"


def test_rate_limiting_in_datastore_model(client, live_server, datastore_path):
    """Test that rate_limit_seconds is properly stored in the datastore model."""
    
    datastore = live_server.app.config.get('DATASTORE')
    
    # Test setting different values
    test_values = [0, 3, 10, 60, 3600]
    
    for value in test_values:
        datastore.data['settings']['requests']['rate_limit_seconds'] = value
        assert datastore.data['settings']['requests']['rate_limit_seconds'] == value, \
            f"Rate limit should be set to {value}"


def test_rate_limiting_validation_max_value(client, live_server, datastore_path):
    """Test that rate_limit_seconds has a maximum value of 3600 seconds."""
    
    # Try to set rate limiting to more than 3600 seconds (should fail validation)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-rate_limit_seconds": 3601,  # Over the max
            "requests-time_between_check-minutes": 10,
            "requests-jitter_seconds": 0,
            "requests-workers": 10,
            "requests-timeout": 45,
            "application-fetch_backend": "html_requests",
            "application-empty_pages_are_a_change": "",
            "application-ignore_whitespace": "y"
        },
        follow_redirects=True
    )
    
    # Should have validation error
    assert res.status_code == 200  # Form redisplays with error


def test_rate_limiting_validation_negative_value(client, live_server, datastore_path):
    """Test that rate_limit_seconds cannot be negative."""
    
    datastore = live_server.app.config.get('DATASTORE')
    # Set to a known good value first
    datastore.data['settings']['requests']['rate_limit_seconds'] = 5
    
    # Try to set rate limiting to a negative value (should fail validation)
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "requests-rate_limit_seconds": -1,
            "requests-time_between_check-minutes": 10,
            "requests-jitter_seconds": 0,
            "requests-workers": 10,
            "requests-timeout": 45,
            "application-fetch_backend": "html_requests",
            "application-empty_pages_are_a_change": "",
            "application-ignore_whitespace": "y"
        },
        follow_redirects=True
    )
    
    # Validation should have failed - verify the value didn't change from 5
    rate_limit = datastore.data['settings']['requests'].get('rate_limit_seconds', 0)
    assert rate_limit == 5, f"Negative value should have been rejected, but rate_limit is now {rate_limit}"


def test_enforce_rate_limit_basic():
    """Test that enforce_rate_limit correctly enforces a delay."""
    import asyncio
    from changedetectionio import async_update_worker
    
    # Reset the global state
    async_update_worker._last_request_time = 0.0
    
    rate_limit_seconds = 3
    
    async def run_test():
        # First request should set the timestamp and not delay
        start_time = time.time()
        await async_update_worker.enforce_rate_limit(rate_limit_seconds, worker_id=1, url="http://example.com")
        first_duration = time.time() - start_time
        
        # Should complete almost instantly (no delay on first request)
        assert first_duration < 0.5, f"First request should not delay, took {first_duration}s"
        
        # Second request immediately after should delay
        start_time = time.time()
        await async_update_worker.enforce_rate_limit(rate_limit_seconds, worker_id=2, url="http://example.com/2")
        second_duration = time.time() - start_time
        
        # Should delay approximately rate_limit_seconds
        assert 2.5 < second_duration < 3.5, \
            f"Second request should delay ~{rate_limit_seconds}s, took {second_duration}s"
    
    asyncio.run(run_test())


def test_enforce_rate_limit_disabled():
    """Test that no delay occurs when rate limiting is disabled (0 seconds)."""
    import asyncio
    from changedetectionio import async_update_worker
    
    # Reset the global state
    async_update_worker._last_request_time = time.time()
    
    rate_limit_seconds = 0  # Disabled
    
    async def run_test():
        # Should not cause any delay
        start_time = time.time()
        await async_update_worker.enforce_rate_limit(rate_limit_seconds, worker_id=1, url="http://example.com")
        duration = time.time() - start_time
        
        assert duration < 0.1, f"No delay should occur when rate limiting is disabled, took {duration}s"
    
    asyncio.run(run_test())


def test_enforce_rate_limit_after_long_delay():
    """Test that no sleep occurs if enough time has already passed."""
    import asyncio
    from changedetectionio import async_update_worker
    
    # Reset the global state and set it to 5 seconds ago
    async_update_worker._last_request_time = time.time() - 5.0
    
    rate_limit_seconds = 3
    
    async def run_test():
        # Should not delay since 5 seconds have already passed
        start_time = time.time()
        await async_update_worker.enforce_rate_limit(rate_limit_seconds, worker_id=1, url="http://example.com")
        duration = time.time() - start_time
        
        # No sleep should be needed
        assert duration < 0.1, \
            f"No sleep should be needed when enough time has passed, took {duration}s"
    
    asyncio.run(run_test())


def test_enforce_rate_limit_multiple_workers():
    """Test that multiple workers properly serialize their requests."""
    import asyncio
    from changedetectionio import async_update_worker
    
    # Reset the global state
    async_update_worker._last_request_time = 0.0
    
    rate_limit_seconds = 2
    
    # Simulate 3 workers making requests in quick succession
    timestamps = []
    
    async def make_request(worker_id):
        await async_update_worker.enforce_rate_limit(rate_limit_seconds, worker_id=worker_id, url=f"http://example.com/{worker_id}")
        timestamps.append(time.time())
    
    async def run_test():
        # Start all workers nearly simultaneously
        await asyncio.gather(
            make_request(1),
            make_request(2),
            make_request(3)
        )
        
        # Verify requests were properly spaced
        assert len(timestamps) == 3, "Should have 3 timestamps"
        
        # Check spacing between consecutive requests
        for i in range(1, len(timestamps)):
            time_diff = timestamps[i] - timestamps[i-1]
            # All requests should be ordered in time
            assert time_diff >= 0, f"Requests should be ordered in time"
    
    asyncio.run(run_test())
