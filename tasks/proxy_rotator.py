"""
Proxy Rotation Middleware for TicketWatch

This module provides per-request proxy rotation functionality for the TicketWatch
ticket monitoring platform. It supports loading proxies from files or environment
variables, and supports separate pools for residential and datacenter proxies.

Usage:
    from proxy_rotator import ProxyRotator

    rotator = ProxyRotator()
    proxy_url = rotator.get_next_proxy()  # Returns next proxy in rotation
"""

import os
import random
import threading
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum

# Try to import loguru, fall back to standard logging if not available
try:
    from loguru import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)


class ProxyType(Enum):
    """Types of proxies supported."""
    RESIDENTIAL = "residential"
    DATACENTER = "datacenter"
    MIXED = "mixed"  # For combined pools


@dataclass
class Proxy:
    """Represents a single proxy configuration."""
    url: str
    proxy_type: ProxyType = ProxyType.MIXED
    label: str = ""

    def __post_init__(self):
        if not self.label:
            self.label = self.url.split('@')[-1] if '@' in self.url else self.url


@dataclass
class ProxyPool:
    """A pool of proxies with rotation support."""
    name: str
    proxies: List[Proxy] = field(default_factory=list)
    current_index: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_proxy(self, proxy: Proxy):
        """Add a proxy to the pool."""
        self.proxies.append(proxy)

    def get_next(self) -> Optional[Proxy]:
        """Get the next proxy in round-robin rotation (thread-safe)."""
        if not self.proxies:
            return None

        with self._lock:
            proxy = self.proxies[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.proxies)
            return proxy

    def get_random(self) -> Optional[Proxy]:
        """Get a random proxy from the pool."""
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    def __len__(self):
        return len(self.proxies)


class ProxyRotator:
    """
    Proxy rotation middleware that manages multiple proxy pools and provides
    per-request proxy rotation.

    Supports loading proxies from:
    - Environment variables (PROXY_LIST, RESIDENTIAL_PROXIES, DATACENTER_PROXIES)
    - Files specified by PROXY_LIST_PATH, RESIDENTIAL_PROXY_PATH, DATACENTER_PROXY_PATH
    - Direct configuration via add_proxy() method

    Proxy format in files/env vars:
    - One proxy per line
    - Format: protocol://[user:pass@]host:port
    - Example: http://user:pass@proxy.example.com:8080
    - Example: socks5://192.168.1.1:1080
    """

    _instance: Optional['ProxyRotator'] = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure consistent proxy rotation across the app."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the proxy rotator and load proxies from configured sources."""
        if self._initialized:
            return

        self._initialized = True
        self.pools: Dict[str, ProxyPool] = {
            'default': ProxyPool(name='default'),
            'residential': ProxyPool(name='residential'),
            'datacenter': ProxyPool(name='datacenter'),
        }
        self._rotation_lock = threading.Lock()

        # Load proxies from all configured sources
        self._load_proxies()

        total_proxies = sum(len(pool) for pool in self.pools.values())
        logger.info(f"ProxyRotator initialized with {total_proxies} total proxies")
        for name, pool in self.pools.items():
            if len(pool) > 0:
                logger.info(f"  - {name}: {len(pool)} proxies")

    def _load_proxies(self):
        """Load proxies from all configured sources."""
        # Load from general proxy list (file or env)
        self._load_from_env_or_file(
            env_var='PROXY_LIST',
            path_env_var='PROXY_LIST_PATH',
            pool_name='default',
            proxy_type=ProxyType.MIXED
        )

        # Load from residential proxy list
        self._load_from_env_or_file(
            env_var='RESIDENTIAL_PROXIES',
            path_env_var='RESIDENTIAL_PROXY_PATH',
            pool_name='residential',
            proxy_type=ProxyType.RESIDENTIAL
        )

        # Load from datacenter proxy list
        self._load_from_env_or_file(
            env_var='DATACENTER_PROXIES',
            path_env_var='DATACENTER_PROXY_PATH',
            pool_name='datacenter',
            proxy_type=ProxyType.DATACENTER
        )

        # If residential/datacenter pools are populated, add them to default pool too
        # This allows get_next_proxy() to use all available proxies
        for pool_name in ['residential', 'datacenter']:
            for proxy in self.pools[pool_name].proxies:
                if proxy not in self.pools['default'].proxies:
                    self.pools['default'].add_proxy(proxy)

    def _load_from_env_or_file(
        self,
        env_var: str,
        path_env_var: str,
        pool_name: str,
        proxy_type: ProxyType
    ):
        """Load proxies from environment variable or file."""
        pool = self.pools[pool_name]

        # First try to load from file path
        file_path = os.getenv(path_env_var)
        if file_path and os.path.isfile(file_path):
            self._load_from_file(file_path, pool, proxy_type)
            return

        # Then try to load from environment variable directly
        proxy_list_str = os.getenv(env_var)
        if proxy_list_str:
            self._parse_proxy_list(proxy_list_str, pool, proxy_type)

    def _load_from_file(self, file_path: str, pool: ProxyPool, proxy_type: ProxyType):
        """Load proxies from a file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                self._parse_proxy_list(content, pool, proxy_type)
            logger.info(f"Loaded {len(pool)} proxies from {file_path}")
        except Exception as e:
            logger.error(f"Failed to load proxies from {file_path}: {e}")

    def _parse_proxy_list(self, content: str, pool: ProxyPool, proxy_type: ProxyType):
        """Parse a proxy list string (newline or comma separated)."""
        # Support both newline and comma-separated formats
        lines = content.replace(',', '\n').split('\n')

        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue

            # Normalize the proxy URL
            proxy_url = self._normalize_proxy_url(line)
            if proxy_url:
                proxy = Proxy(url=proxy_url, proxy_type=proxy_type)
                pool.add_proxy(proxy)

    def _normalize_proxy_url(self, proxy_str: str) -> Optional[str]:
        """
        Normalize a proxy string to a standard URL format.

        Supports formats:
        - http://host:port
        - http://user:pass@host:port
        - host:port (assumes http://)
        - user:pass@host:port (assumes http://)
        - socks5://host:port
        """
        proxy_str = proxy_str.strip()
        if not proxy_str:
            return None

        # If no protocol specified, assume http://
        if not any(proxy_str.startswith(p) for p in ['http://', 'https://', 'socks4://', 'socks5://']):
            proxy_str = f'http://{proxy_str}'

        return proxy_str

    def add_proxy(
        self,
        url: str,
        proxy_type: ProxyType = ProxyType.MIXED,
        pool_name: str = 'default'
    ):
        """Manually add a proxy to a specific pool."""
        normalized_url = self._normalize_proxy_url(url)
        if normalized_url:
            proxy = Proxy(url=normalized_url, proxy_type=proxy_type)
            if pool_name in self.pools:
                self.pools[pool_name].add_proxy(proxy)
            else:
                self.pools['default'].add_proxy(proxy)

    def get_next_proxy(self, pool_name: str = 'default') -> Optional[str]:
        """
        Get the next proxy URL in rotation.

        Args:
            pool_name: Name of the pool to get proxy from ('default', 'residential', 'datacenter')

        Returns:
            Proxy URL string or None if no proxies available
        """
        pool = self.pools.get(pool_name, self.pools['default'])

        # Fall back to default pool if requested pool is empty
        if not pool.proxies and pool_name != 'default':
            pool = self.pools['default']

        proxy = pool.get_next()
        if proxy:
            logger.debug(f"Selected proxy from {pool.name} pool: {proxy.label}")
            return proxy.url

        return None

    def get_random_proxy(self, pool_name: str = 'default') -> Optional[str]:
        """
        Get a random proxy URL from the specified pool.

        Args:
            pool_name: Name of the pool to get proxy from

        Returns:
            Proxy URL string or None if no proxies available
        """
        pool = self.pools.get(pool_name, self.pools['default'])

        if not pool.proxies and pool_name != 'default':
            pool = self.pools['default']

        proxy = pool.get_random()
        if proxy:
            logger.debug(f"Selected random proxy from {pool.name} pool: {proxy.label}")
            return proxy.url

        return None

    def get_proxy_for_watch(self, watch_uuid: str = None) -> Optional[str]:
        """
        Get the next proxy for a watch request.

        This is the main method to use for per-request proxy rotation.

        Args:
            watch_uuid: Optional watch UUID for logging purposes

        Returns:
            Proxy URL string or None if no proxies available
        """
        proxy_url = self.get_next_proxy()
        if proxy_url and watch_uuid:
            logger.debug(f"Assigned proxy for watch {watch_uuid}: {proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url}")
        return proxy_url

    def get_pool_stats(self) -> Dict[str, Any]:
        """Get statistics about proxy pools."""
        stats = {}
        for name, pool in self.pools.items():
            stats[name] = {
                'count': len(pool),
                'current_index': pool.current_index,
            }
        return stats

    def reload_proxies(self):
        """Reload proxies from configured sources."""
        logger.info("Reloading proxy configuration...")
        for pool in self.pools.values():
            pool.proxies.clear()
            pool.current_index = 0
        self._load_proxies()

    @property
    def has_proxies(self) -> bool:
        """Check if any proxies are available."""
        return any(len(pool) > 0 for pool in self.pools.values())

    @property
    def total_proxy_count(self) -> int:
        """Get total number of unique proxies across all pools."""
        # Use default pool count since residential/datacenter are also added there
        return len(self.pools['default'])


# Module-level function for easy access
def get_rotated_proxy(watch_uuid: str = None) -> Optional[str]:
    """
    Convenience function to get the next rotated proxy.

    Args:
        watch_uuid: Optional watch UUID for logging

    Returns:
        Proxy URL string or None if no proxies configured
    """
    rotator = ProxyRotator()
    return rotator.get_proxy_for_watch(watch_uuid)


def get_proxy_rotator() -> ProxyRotator:
    """Get the singleton ProxyRotator instance."""
    return ProxyRotator()
