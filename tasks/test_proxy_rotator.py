"""
Tests for the Proxy Rotation Middleware

These tests verify the functionality of the ProxyRotator class and its
ability to load, manage, and rotate through proxy lists.
"""

import os
import sys
import tempfile
from unittest.mock import patch

import pytest

from tasks.proxy_rotator import (
    DEFAULT_RECOVERY_TIMEOUT,
    Proxy,
    ProxyHealth,
    ProxyRotator,
    ProxyType,
    get_proxy_rotator,
    get_rotated_proxy,
)


# Reset the singleton before each test module
@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the ProxyRotator singleton before each test."""
    ProxyRotator._instance = None
    yield
    ProxyRotator._instance = None


class TestProxyRotator:
    """Tests for the ProxyRotator class."""

    def test_singleton_pattern(self):
        """Verify that ProxyRotator uses singleton pattern."""
        from proxy_rotator import ProxyRotator
        rotator1 = ProxyRotator()
        rotator2 = ProxyRotator()
        assert rotator1 is rotator2

    def test_empty_initialization(self):
        """Test initialization with no proxy sources configured."""
        from proxy_rotator import ProxyRotator

        # Clear any environment variables
        with patch.dict(os.environ, {}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            assert not rotator.has_proxies
            assert rotator.total_proxy_count == 0
            assert rotator.get_next_proxy() is None

    def test_load_from_env_variable(self):
        """Test loading proxies from PROXY_LIST environment variable."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            assert rotator.has_proxies
            assert rotator.total_proxy_count == 2

    def test_load_from_file(self):
        """Test loading proxies from a file."""
        from proxy_rotator import ProxyRotator

        # Create a temporary proxy file
        proxy_content = """# This is a comment
http://user:pass@proxy1.example.com:8080
http://proxy2.example.com:3128
socks5://192.168.1.1:1080
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(proxy_content)
            temp_path = f.name

        try:
            with patch.dict(os.environ, {'PROXY_LIST_PATH': temp_path}, clear=True):
                ProxyRotator._instance = None
                rotator = ProxyRotator()

                assert rotator.has_proxies
                assert rotator.total_proxy_count == 3
        finally:
            os.unlink(temp_path)

    def test_round_robin_rotation(self):
        """Test that proxies are rotated in round-robin fashion."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080\nhttp://proxy2.com:8080\nhttp://proxy3.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Get proxies in sequence
            proxy1 = rotator.get_next_proxy()
            proxy2 = rotator.get_next_proxy()
            proxy3 = rotator.get_next_proxy()
            proxy4 = rotator.get_next_proxy()  # Should cycle back to first

            assert proxy1 == "http://proxy1.com:8080"
            assert proxy2 == "http://proxy2.com:8080"
            assert proxy3 == "http://proxy3.com:8080"
            assert proxy4 == "http://proxy1.com:8080"  # Cycled back

    def test_residential_and_datacenter_pools(self):
        """Test separate residential and datacenter proxy pools."""
        from proxy_rotator import ProxyRotator

        residential = "http://residential1.com:8080,http://residential2.com:8080"
        datacenter = "http://datacenter1.com:8080,http://datacenter2.com:8080"

        with patch.dict(os.environ, {
            'RESIDENTIAL_PROXIES': residential,
            'DATACENTER_PROXIES': datacenter
        }, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Check pool sizes
            stats = rotator.get_pool_stats()
            assert stats['residential']['count'] == 2
            assert stats['datacenter']['count'] == 2
            # Default pool should have all proxies
            assert stats['default']['count'] == 4

            # Get from specific pools
            res_proxy = rotator.get_next_proxy(pool_name='residential')
            assert 'residential' in res_proxy

            dc_proxy = rotator.get_next_proxy(pool_name='datacenter')
            assert 'datacenter' in dc_proxy

    def test_normalize_proxy_url(self):
        """Test proxy URL normalization."""
        from proxy_rotator import ProxyRotator

        rotator = ProxyRotator()

        # Test various formats
        assert rotator._normalize_proxy_url("proxy.com:8080") == "http://proxy.com:8080"
        assert rotator._normalize_proxy_url("http://proxy.com:8080") == "http://proxy.com:8080"
        assert rotator._normalize_proxy_url("socks5://proxy.com:1080") == "socks5://proxy.com:1080"
        assert rotator._normalize_proxy_url("user:pass@proxy.com:8080") == "http://user:pass@proxy.com:8080"
        assert rotator._normalize_proxy_url("  http://proxy.com:8080  ") == "http://proxy.com:8080"
        assert rotator._normalize_proxy_url("") is None
        assert rotator._normalize_proxy_url("   ") is None

    def test_add_proxy_manually(self):
        """Test manually adding proxies."""
        from proxy_rotator import ProxyRotator

        with patch.dict(os.environ, {}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            rotator.add_proxy("http://manual1.com:8080", ProxyType.RESIDENTIAL, 'residential')
            rotator.add_proxy("http://manual2.com:8080", ProxyType.DATACENTER, 'datacenter')

            stats = rotator.get_pool_stats()
            assert stats['residential']['count'] == 1
            assert stats['datacenter']['count'] == 1

    def test_get_random_proxy(self):
        """Test random proxy selection."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080,http://proxy3.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Get random proxies - they should all be valid
            for _ in range(10):
                proxy = rotator.get_random_proxy()
                assert proxy is not None
                assert proxy.startswith("http://proxy")

    def test_get_proxy_for_watch(self):
        """Test the main method for getting proxies for watch requests."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            proxy = rotator.get_proxy_for_watch(watch_uuid="test-uuid-123")
            assert proxy is not None

    def test_reload_proxies(self):
        """Test reloading proxy configuration."""
        from proxy_rotator import ProxyRotator

        with patch.dict(os.environ, {'PROXY_LIST': "http://proxy1.com:8080"}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            assert rotator.total_proxy_count == 1

            # Modify env and reload
            with patch.dict(os.environ, {'PROXY_LIST': "http://proxy1.com:8080,http://proxy2.com:8080"}):
                rotator.reload_proxies()
                assert rotator.total_proxy_count == 2

    def test_fallback_to_default_pool(self):
        """Test fallback to default pool when requested pool is empty."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://default1.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Request from empty residential pool should fall back to default
            proxy = rotator.get_next_proxy(pool_name='residential')
            assert proxy == "http://default1.com:8080"

    def test_thread_safety(self):
        """Test thread safety of proxy rotation."""
        import threading
        import time

        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080,http://proxy3.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            results = []

            def get_proxies(count):
                for _ in range(count):
                    proxy = rotator.get_next_proxy()
                    results.append(proxy)
                    time.sleep(0.001)

            threads = [threading.Thread(target=get_proxies, args=(10,)) for _ in range(5)]

            for t in threads:
                t.start()
            for t in threads:
                t.join()

            # All results should be valid proxies
            assert len(results) == 50
            for proxy in results:
                assert proxy is not None
                assert proxy.startswith("http://proxy")


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_rotated_proxy(self):
        """Test the get_rotated_proxy convenience function."""
        from proxy_rotator import ProxyRotator

        test_proxies = "http://proxy1.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            proxy = get_rotated_proxy(watch_uuid="test-123")
            assert proxy == "http://proxy1.com:8080"

    def test_get_proxy_rotator(self):
        """Test the get_proxy_rotator convenience function."""
        from proxy_rotator import ProxyRotator

        with patch.dict(os.environ, {}, clear=True):
            ProxyRotator._instance = None
            rotator = get_proxy_rotator()
            assert isinstance(rotator, ProxyRotator)


class TestProxyTypes:
    """Tests for proxy type handling."""

    def test_proxy_type_enum(self):
        """Test ProxyType enum values."""

        assert ProxyType.RESIDENTIAL.value == "residential"
        assert ProxyType.DATACENTER.value == "datacenter"
        assert ProxyType.MIXED.value == "mixed"

    def test_proxy_dataclass(self):
        """Test Proxy dataclass."""
        from proxy_rotator import Proxy

        proxy = Proxy(
            url="http://user:pass@proxy.com:8080",
            proxy_type=ProxyType.RESIDENTIAL
        )

        assert proxy.url == "http://user:pass@proxy.com:8080"
        assert proxy.proxy_type == ProxyType.RESIDENTIAL
        # Label should be extracted from URL (host part)
        assert "proxy.com:8080" in proxy.label


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_invalid_file_path(self):
        """Test handling of invalid file path."""
        from proxy_rotator import ProxyRotator

        with patch.dict(os.environ, {'PROXY_LIST_PATH': '/nonexistent/path/proxies.txt'}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Should not raise, just have no proxies
            assert not rotator.has_proxies

    def test_empty_file(self):
        """Test handling of empty proxy file."""
        from proxy_rotator import ProxyRotator

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("")  # Empty file
            temp_path = f.name

        try:
            with patch.dict(os.environ, {'PROXY_LIST_PATH': temp_path}, clear=True):
                ProxyRotator._instance = None
                rotator = ProxyRotator()

                assert not rotator.has_proxies
        finally:
            os.unlink(temp_path)

    def test_comment_only_file(self):
        """Test handling of file with only comments."""
        from proxy_rotator import ProxyRotator

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("# This is a comment\n# Another comment\n")
            temp_path = f.name

        try:
            with patch.dict(os.environ, {'PROXY_LIST_PATH': temp_path}, clear=True):
                ProxyRotator._instance = None
                rotator = ProxyRotator()

                assert not rotator.has_proxies
        finally:
            os.unlink(temp_path)

    def test_mixed_valid_invalid_proxies(self):
        """Test handling of file with mixed valid and invalid entries."""
        from proxy_rotator import ProxyRotator

        content = """
# Comment line
http://valid1.com:8080


http://valid2.com:8080
# Another comment
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            with patch.dict(os.environ, {'PROXY_LIST_PATH': temp_path}, clear=True):
                ProxyRotator._instance = None
                rotator = ProxyRotator()

                # Should only have the 2 valid proxies
                assert rotator.total_proxy_count == 2
        finally:
            os.unlink(temp_path)


class TestProxyHealth:
    """Tests for proxy health tracking functionality."""

    def test_proxy_health_enum(self):
        """Test ProxyHealth enum values."""
        assert ProxyHealth.HEALTHY.value == "healthy"
        assert ProxyHealth.DEAD.value == "dead"

    def test_proxy_initial_health(self):
        """Test that proxies start as healthy."""
        proxy = Proxy(url="http://proxy.com:8080")
        assert proxy.health == ProxyHealth.HEALTHY
        assert proxy.failure_count == 0
        assert proxy.consecutive_failures == 0
        assert proxy.is_healthy()

    def test_proxy_mark_failed(self):
        """Test marking a proxy as failed."""
        proxy = Proxy(url="http://proxy.com:8080")

        proxy.mark_failed()
        assert proxy.failure_count == 1
        assert proxy.consecutive_failures == 1
        assert proxy.last_failure_time > 0

        proxy.mark_failed()
        assert proxy.failure_count == 2
        assert proxy.consecutive_failures == 2

    def test_proxy_mark_success_resets_consecutive_failures(self):
        """Test that success resets consecutive failure count."""
        proxy = Proxy(url="http://proxy.com:8080")

        proxy.mark_failed()
        proxy.mark_failed()
        assert proxy.consecutive_failures == 2

        proxy.mark_success()
        assert proxy.consecutive_failures == 0
        assert proxy.failure_count == 2  # Total count not reset
        assert proxy.health == ProxyHealth.HEALTHY

    def test_proxy_mark_dead(self):
        """Test marking a proxy as dead."""
        proxy = Proxy(url="http://proxy.com:8080")

        proxy.mark_dead()
        assert proxy.health == ProxyHealth.DEAD
        assert proxy.last_failure_time > 0

    def test_proxy_recovery_after_timeout(self):
        """Test that dead proxies recover after timeout."""
        import time

        proxy = Proxy(url="http://proxy.com:8080")
        proxy.mark_dead()

        # Should be dead immediately
        assert not proxy.is_healthy(recovery_timeout=1.0)

        # Simulate time passing
        proxy.last_failure_time = time.time() - 2.0  # 2 seconds ago

        # Should be healthy now (recovery timeout of 1 second)
        assert proxy.is_healthy(recovery_timeout=1.0)
        assert proxy.health == ProxyHealth.HEALTHY
        assert proxy.consecutive_failures == 0


class TestProxyPoolHealth:
    """Tests for proxy pool health management."""

    def test_get_next_skips_dead_proxies(self):
        """Test that get_next skips dead proxies."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy1 = Proxy(url="http://proxy1.com:8080")
        proxy2 = Proxy(url="http://proxy2.com:8080")
        proxy3 = Proxy(url="http://proxy3.com:8080")

        pool.add_proxy(proxy1)
        pool.add_proxy(proxy2)
        pool.add_proxy(proxy3)

        # Mark proxy1 and proxy2 as dead
        proxy1.mark_dead()
        proxy2.mark_dead()

        # Should skip dead proxies and return proxy3
        result = pool.get_next(skip_dead=True)
        assert result.url == "http://proxy3.com:8080"

    def test_get_next_returns_none_when_all_dead(self):
        """Test get_next returns None when all proxies are dead."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy1 = Proxy(url="http://proxy1.com:8080")
        proxy2 = Proxy(url="http://proxy2.com:8080")

        pool.add_proxy(proxy1)
        pool.add_proxy(proxy2)

        proxy1.mark_dead()
        proxy2.mark_dead()

        result = pool.get_next(skip_dead=True)
        assert result is None

    def test_get_next_skip_dead_false(self):
        """Test get_next with skip_dead=False returns dead proxies."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy1 = Proxy(url="http://proxy1.com:8080")

        pool.add_proxy(proxy1)
        proxy1.mark_dead()

        # With skip_dead=False, should still return the dead proxy
        result = pool.get_next(skip_dead=False)
        assert result.url == "http://proxy1.com:8080"

    def test_get_random_skips_dead_proxies(self):
        """Test that get_random only selects from healthy proxies."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy1 = Proxy(url="http://proxy1.com:8080")
        proxy2 = Proxy(url="http://proxy2.com:8080")

        pool.add_proxy(proxy1)
        pool.add_proxy(proxy2)

        proxy1.mark_dead()

        # Should only return proxy2
        for _ in range(10):
            result = pool.get_random(skip_dead=True)
            assert result.url == "http://proxy2.com:8080"

    def test_get_random_returns_none_when_all_dead(self):
        """Test get_random returns None when all proxies are dead."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy = Proxy(url="http://proxy.com:8080")
        pool.add_proxy(proxy)
        proxy.mark_dead()

        result = pool.get_random(skip_dead=True)
        assert result is None

    def test_get_proxy_by_url(self):
        """Test finding proxy by URL."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        proxy = Proxy(url="http://proxy.com:8080")
        pool.add_proxy(proxy)

        found = pool.get_proxy_by_url("http://proxy.com:8080")
        assert found is proxy

        not_found = pool.get_proxy_by_url("http://other.com:8080")
        assert not_found is None

    def test_get_healthy_count(self):
        """Test getting count of healthy proxies."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        pool.add_proxy(Proxy(url="http://proxy1.com:8080"))
        pool.add_proxy(Proxy(url="http://proxy2.com:8080"))
        pool.add_proxy(Proxy(url="http://proxy3.com:8080"))

        assert pool.get_healthy_count() == 3

        pool.proxies[0].mark_dead()
        assert pool.get_healthy_count() == 2

    def test_get_dead_count(self):
        """Test getting count of dead proxies."""
        from proxy_rotator import ProxyPool

        pool = ProxyPool(name='test')
        pool.add_proxy(Proxy(url="http://proxy1.com:8080"))
        pool.add_proxy(Proxy(url="http://proxy2.com:8080"))

        assert pool.get_dead_count() == 0

        pool.proxies[0].mark_dead()
        pool.proxies[1].mark_dead()
        assert pool.get_dead_count() == 2


class TestProxyRotatorHealth:
    """Tests for ProxyRotator health management methods."""

    def test_report_proxy_failure(self):
        """Test reporting proxy failures."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Report failures below threshold
            result = rotator.report_proxy_failure("http://proxy1.com:8080", mark_dead_after=3)
            assert result is False

            result = rotator.report_proxy_failure("http://proxy1.com:8080", mark_dead_after=3)
            assert result is False

            # Third failure should mark as dead
            result = rotator.report_proxy_failure("http://proxy1.com:8080", mark_dead_after=3)
            assert result is True

            # Verify proxy is now dead
            dead_proxies = rotator.get_dead_proxies()
            assert "http://proxy1.com:8080" in dead_proxies

    def test_report_proxy_success(self):
        """Test reporting proxy success resets failure count."""
        test_proxies = "http://proxy.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Record some failures
            rotator.report_proxy_failure("http://proxy.com:8080")
            rotator.report_proxy_failure("http://proxy.com:8080")

            # Report success
            rotator.report_proxy_success("http://proxy.com:8080")

            # Proxy should be healthy
            proxy = rotator.pools['default'].get_proxy_by_url("http://proxy.com:8080")
            assert proxy.consecutive_failures == 0
            assert proxy.health == ProxyHealth.HEALTHY

    def test_mark_proxy_dead(self):
        """Test explicitly marking a proxy as dead."""
        test_proxies = "http://proxy.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            result = rotator.mark_proxy_dead("http://proxy.com:8080")
            assert result is True

            dead_proxies = rotator.get_dead_proxies()
            assert "http://proxy.com:8080" in dead_proxies

    def test_mark_proxy_dead_not_found(self):
        """Test marking non-existent proxy as dead returns False."""
        with patch.dict(os.environ, {}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            result = rotator.mark_proxy_dead("http://nonexistent.com:8080")
            assert result is False

    def test_get_healthy_proxy_count(self):
        """Test getting healthy proxy count."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080,http://proxy3.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            assert rotator.get_healthy_proxy_count() == 3

            rotator.mark_proxy_dead("http://proxy1.com:8080")
            assert rotator.get_healthy_proxy_count() == 2

    def test_get_dead_proxies(self):
        """Test getting list of dead proxies."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            assert rotator.get_dead_proxies() == []

            rotator.mark_proxy_dead("http://proxy1.com:8080")
            dead = rotator.get_dead_proxies()
            assert len(dead) == 1
            assert "http://proxy1.com:8080" in dead

    def test_revive_all_proxies(self):
        """Test reviving all dead proxies."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Mark all as dead
            rotator.mark_proxy_dead("http://proxy1.com:8080")
            rotator.mark_proxy_dead("http://proxy2.com:8080")

            assert rotator.get_healthy_proxy_count() == 0

            # Revive all
            rotator.revive_all_proxies()

            assert rotator.get_healthy_proxy_count() == 2
            assert rotator.get_dead_proxies() == []

    def test_set_recovery_timeout(self):
        """Test setting recovery timeout."""
        test_proxies = "http://proxy.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            rotator.set_recovery_timeout(60.0)

            for pool in rotator.pools.values():
                assert pool.recovery_timeout == 60.0

    def test_set_recovery_timeout_specific_pool(self):
        """Test setting recovery timeout for specific pool."""
        test_proxies = "http://proxy.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            rotator.set_recovery_timeout(30.0, pool_name='default')

            assert rotator.pools['default'].recovery_timeout == 30.0
            assert rotator.pools['residential'].recovery_timeout == DEFAULT_RECOVERY_TIMEOUT

    def test_get_next_proxy_skips_dead(self):
        """Test that get_next_proxy skips dead proxies."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Mark first proxy as dead
            rotator.mark_proxy_dead("http://proxy1.com:8080")

            # Should only get proxy2
            for _ in range(5):
                proxy = rotator.get_next_proxy()
                assert proxy == "http://proxy2.com:8080"

    def test_get_next_proxy_returns_none_when_all_dead(self):
        """Test get_next_proxy returns None when all proxies are dead."""
        test_proxies = "http://proxy.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            rotator.mark_proxy_dead("http://proxy.com:8080")

            proxy = rotator.get_next_proxy()
            assert proxy is None

    def test_pool_stats_include_health_info(self):
        """Test that pool stats include health information."""
        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            rotator.mark_proxy_dead("http://proxy1.com:8080")

            stats = rotator.get_pool_stats()

            assert 'healthy_count' in stats['default']
            assert 'dead_count' in stats['default']
            assert stats['default']['healthy_count'] == 1
            assert stats['default']['dead_count'] == 1

    def test_proxy_recovery_in_rotation(self):
        """Test that dead proxies can recover and be used again."""
        import time

        test_proxies = "http://proxy1.com:8080,http://proxy2.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            rotator = ProxyRotator()

            # Set short recovery timeout
            rotator.set_recovery_timeout(0.1)  # 100ms

            # Mark proxy1 as dead
            rotator.mark_proxy_dead("http://proxy1.com:8080")

            # Initially should only get proxy2
            proxy = rotator.get_next_proxy()
            assert proxy == "http://proxy2.com:8080"

            # Wait for recovery timeout
            time.sleep(0.15)

            # Now should be able to get proxy1 again
            # Need to cycle through to find it
            proxies_seen = set()
            for _ in range(4):
                p = rotator.get_next_proxy()
                proxies_seen.add(p)

            assert "http://proxy1.com:8080" in proxies_seen


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
