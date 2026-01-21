"""
Tests for the Proxy Rotation Middleware

These tests verify the functionality of the ProxyRotator class and its
ability to load, manage, and rotate through proxy lists.
"""

import os
import sys
import tempfile
import pytest
from unittest.mock import patch, MagicMock

# Add the tasks directory to the path so we can import proxy_rotator
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from proxy_rotator import ProxyRotator, ProxyType, Proxy, get_rotated_proxy, get_proxy_rotator


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
        from proxy_rotator import ProxyRotator, ProxyType

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
        from proxy_rotator import ProxyRotator
        import threading
        import time

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
        from proxy_rotator import get_rotated_proxy, ProxyRotator

        test_proxies = "http://proxy1.com:8080"

        with patch.dict(os.environ, {'PROXY_LIST': test_proxies}, clear=True):
            ProxyRotator._instance = None
            proxy = get_rotated_proxy(watch_uuid="test-123")
            assert proxy == "http://proxy1.com:8080"

    def test_get_proxy_rotator(self):
        """Test the get_proxy_rotator convenience function."""
        from proxy_rotator import get_proxy_rotator, ProxyRotator

        with patch.dict(os.environ, {}, clear=True):
            ProxyRotator._instance = None
            rotator = get_proxy_rotator()
            assert isinstance(rotator, ProxyRotator)


class TestProxyTypes:
    """Tests for proxy type handling."""

    def test_proxy_type_enum(self):
        """Test ProxyType enum values."""
        from proxy_rotator import ProxyType

        assert ProxyType.RESIDENTIAL.value == "residential"
        assert ProxyType.DATACENTER.value == "datacenter"
        assert ProxyType.MIXED.value == "mixed"

    def test_proxy_dataclass(self):
        """Test Proxy dataclass."""
        from proxy_rotator import Proxy, ProxyType

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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
