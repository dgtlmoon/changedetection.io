"""
Proxy Rotation Middleware for TicketWatch

This module provides per-request proxy rotation functionality for the TicketWatch
ticket monitoring platform. It supports loading proxies from files or environment
variables, and supports separate pools for residential and datacenter proxies.

Features:
- Load proxies from environment variables or files
- Separate residential and datacenter proxy pools
- Round-robin and random proxy selection
- Dead proxy detection and automatic skipping
- Proxy recovery after configurable timeout period
- Comprehensive logging of proxy usage and failures

Usage:
    from changedetectionio.proxy_rotator import ProxyRotator

    rotator = ProxyRotator()
    proxy_url = rotator.get_next_proxy()  # Returns next proxy in rotation

    # Report proxy failures for dead detection
    rotator.report_proxy_failure(proxy_url)

    # Report successes to reset failure counters
    rotator.report_proxy_success(proxy_url)
"""

import os
import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

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


class ProxyHealth(Enum):
    """Health status of a proxy."""
    HEALTHY = "healthy"
    DEAD = "dead"


# Default recovery timeout in seconds (5 minutes)
DEFAULT_RECOVERY_TIMEOUT = 300


@dataclass
class Proxy:
    """Represents a single proxy configuration with health tracking."""
    url: str
    proxy_type: ProxyType = ProxyType.MIXED
    label: str = ""
    health: ProxyHealth = ProxyHealth.HEALTHY
    failure_count: int = 0
    last_failure_time: float = 0.0
    consecutive_failures: int = 0

    def __post_init__(self):
        if not self.label:
            self.label = self.url.split('@')[-1] if '@' in self.url else self.url

    def mark_failed(self):
        """Mark this proxy as having failed a request."""
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_time = time.time()
        logger.debug(
            f"Proxy failure: {self.label} "
            f"(consecutive: {self.consecutive_failures}, total: {self.failure_count})"
        )

    def mark_success(self):
        """Mark this proxy as having succeeded. Resets consecutive failure count."""
        self.consecutive_failures = 0
        self.health = ProxyHealth.HEALTHY

    def mark_dead(self):
        """Mark this proxy as dead (should be skipped in rotation)."""
        self.health = ProxyHealth.DEAD
        self.last_failure_time = time.time()
        logger.warning(f"Proxy marked as dead: {self.label}")

    def is_healthy(self, recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT) -> bool:
        """
        Check if proxy is healthy and can be used.

        Dead proxies can recover after the recovery timeout period.

        Args:
            recovery_timeout: Seconds after which a dead proxy can be retried

        Returns:
            True if proxy is healthy or has recovered, False otherwise
        """
        if self.health == ProxyHealth.HEALTHY:
            return True

        # Check if proxy can recover (enough time has passed)
        if self.health == ProxyHealth.DEAD:
            time_since_failure = time.time() - self.last_failure_time
            if time_since_failure >= recovery_timeout:
                logger.info(f"Proxy recovered after timeout: {self.label}")
                self.health = ProxyHealth.HEALTHY
                self.consecutive_failures = 0
                return True

        return False


@dataclass
class ProxyPool:
    """A pool of proxies with rotation support and health tracking."""
    name: str
    proxies: list = field(default_factory=list)
    current_index: int = 0
    recovery_timeout: float = DEFAULT_RECOVERY_TIMEOUT
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_proxy(self, proxy: Proxy):
        """Add a proxy to the pool."""
        self.proxies.append(proxy)

    def get_next(self, skip_dead: bool = True) -> Optional[Proxy]:
        """
        Get the next proxy in round-robin rotation (thread-safe).

        Args:
            skip_dead: If True, skip proxies marked as dead (unless recovered)

        Returns:
            Next healthy proxy, or None if no healthy proxies available
        """
        if not self.proxies:
            return None

        with self._lock:
            if not skip_dead:
                proxy = self.proxies[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.proxies)
                return proxy

            # Try to find a healthy proxy, checking at most len(proxies) times
            for _ in range(len(self.proxies)):
                proxy = self.proxies[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.proxies)

                if proxy.is_healthy(self.recovery_timeout):
                    return proxy

            # No healthy proxies found - return None
            logger.warning(f"No healthy proxies available in {self.name} pool")
            return None

    def get_random(self, skip_dead: bool = True) -> Optional[Proxy]:
        """
        Get a random proxy from the pool.

        Args:
            skip_dead: If True, only select from healthy proxies

        Returns:
            A random healthy proxy, or None if no healthy proxies available
        """
        if not self.proxies:
            return None

        if not skip_dead:
            return random.choice(self.proxies)

        # Filter to healthy proxies
        healthy_proxies = [p for p in self.proxies if p.is_healthy(self.recovery_timeout)]
        if not healthy_proxies:
            logger.warning(f"No healthy proxies available in {self.name} pool for random selection")
            return None

        return random.choice(healthy_proxies)

    def get_proxy_by_url(self, url: str) -> Optional[Proxy]:
        """Find a proxy in this pool by its URL."""
        for proxy in self.proxies:
            if proxy.url == url:
                return proxy
        return None

    def get_healthy_count(self) -> int:
        """Get count of healthy proxies in this pool."""
        return sum(1 for p in self.proxies if p.is_healthy(self.recovery_timeout))

    def get_dead_count(self) -> int:
        """Get count of dead proxies in this pool."""
        return sum(1 for p in self.proxies if p.health == ProxyHealth.DEAD)

    def __len__(self):
        return len(self.proxies)


class ProxyRotator:
    """
    Proxy rotation middleware that manages multiple proxy pools and provides
    per-request proxy rotation with dead proxy detection and recovery.

    Supports loading proxies from:
    - Environment variables (PROXY_LIST, RESIDENTIAL_PROXIES, DATACENTER_PROXIES)
    - Files specified by PROXY_LIST_PATH, RESIDENTIAL_PROXY_PATH, DATACENTER_PROXY_PATH
    - Direct configuration via add_proxy() method

    Proxy format in files/env vars:
    - One proxy per line
    - Format: protocol://[user:pass@]host:port
    - Format: host:port:user:pass (auto-converts to http://user:pass@host:port)
    - Example: http://user:pass@proxy.example.com:8080
    - Example: socks5://192.168.1.1:1080
    - Example: proxy.example.com:8080:myuser:mypass

    Dead Proxy Detection:
    - Report failures with report_proxy_failure()
    - After N consecutive failures, proxy is marked dead
    - Dead proxies are skipped during rotation
    - Dead proxies automatically recover after recovery_timeout

    Example:
        rotator = ProxyRotator()

        # Get a proxy for a request
        proxy_url = rotator.get_next_proxy()

        try:
            response = requests.get(url, proxies={'http': proxy_url, 'https': proxy_url})
            rotator.report_proxy_success(proxy_url)
        except RequestException:
            rotator.report_proxy_failure(proxy_url, mark_dead_after=3)
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
        self.pools: dict[str, ProxyPool] = {
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
            proxy_type=ProxyType.MIXED,
            default_file='proxy_list.txt'
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
        proxy_type: ProxyType,
        default_file: str = None
    ):
        """Load proxies from environment variable or file."""
        pool = self.pools[pool_name]

        # First try to load from file path environment variable
        file_path = os.getenv(path_env_var)
        if file_path and os.path.isfile(file_path):
            self._load_from_file(file_path, pool, proxy_type)
            return

        # Then try to load from environment variable directly
        proxy_list_str = os.getenv(env_var)
        if proxy_list_str:
            self._parse_proxy_list(proxy_list_str, pool, proxy_type)
            return

        # Finally, check for default file in working directory
        if default_file and os.path.isfile(default_file):
            self._load_from_file(default_file, pool, proxy_type)

    def _load_from_file(self, file_path: str, pool: ProxyPool, proxy_type: ProxyType):
        """Load proxies from a file."""
        try:
            with open(file_path, encoding='utf-8') as f:
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
        - host:port:user:pass (assumes http://, converts to user:pass@host:port)
        - socks5://host:port
        """
        proxy_str = proxy_str.strip()
        if not proxy_str:
            return None

        # Check if it already has a protocol
        has_protocol = any(proxy_str.startswith(p) for p in ['http://', 'https://', 'socks4://', 'socks5://'])

        # If no protocol and no @ symbol, check for host:port:user:pass format
        if not has_protocol and '@' not in proxy_str:
            parts = proxy_str.split(':')
            # host:port:user:pass format (4 parts)
            if len(parts) == 4:
                host, port, user, password = parts
                proxy_str = f'http://{user}:{password}@{host}:{port}'
                return proxy_str
            # host:port format (2 parts) - no auth
            elif len(parts) == 2:
                proxy_str = f'http://{proxy_str}'
                return proxy_str

        # If no protocol specified, assume http://
        if not has_protocol:
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
            logger.debug(f"Added proxy to {pool_name} pool: {proxy.label}")

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
            label = proxy_url.split('@')[-1] if '@' in proxy_url else proxy_url
            logger.debug(f"Assigned proxy for watch {watch_uuid}: {label}")
        return proxy_url

    def get_pool_stats(self) -> dict[str, Any]:
        """Get statistics about proxy pools including health information."""
        stats = {}
        for name, pool in self.pools.items():
            stats[name] = {
                'count': len(pool),
                'current_index': pool.current_index,
                'healthy_count': pool.get_healthy_count(),
                'dead_count': pool.get_dead_count(),
                'recovery_timeout': pool.recovery_timeout,
            }
        return stats

    def reload_proxies(self):
        """Reload proxies from configured sources."""
        logger.info("Reloading proxy configuration...")
        for pool in self.pools.values():
            pool.proxies.clear()
            pool.current_index = 0
        self._load_proxies()

    def report_proxy_failure(
        self,
        proxy_url: str,
        mark_dead_after: int = 3,
        pool_name: str = 'default'
    ) -> bool:
        """
        Report a proxy failure and potentially mark it as dead.

        Args:
            proxy_url: The URL of the proxy that failed
            mark_dead_after: Number of consecutive failures before marking dead
            pool_name: Name of the pool containing the proxy

        Returns:
            True if proxy was marked as dead, False otherwise
        """
        pool = self.pools.get(pool_name, self.pools['default'])
        proxy = pool.get_proxy_by_url(proxy_url)

        if not proxy:
            # Try to find in default pool if not in specified pool
            if pool_name != 'default':
                proxy = self.pools['default'].get_proxy_by_url(proxy_url)

        if not proxy:
            logger.warning(f"Could not find proxy to report failure: {proxy_url}")
            return False

        proxy.mark_failed()

        if proxy.consecutive_failures >= mark_dead_after:
            proxy.mark_dead()
            logger.warning(
                f"Proxy marked dead after {mark_dead_after} consecutive failures: {proxy.label}"
            )
            return True

        logger.debug(
            f"Proxy failure recorded: {proxy.label} "
            f"(consecutive failures: {proxy.consecutive_failures}/{mark_dead_after})"
        )
        return False

    def report_proxy_success(self, proxy_url: str, pool_name: str = 'default'):
        """
        Report a successful proxy request, resetting failure counts.

        Args:
            proxy_url: The URL of the proxy that succeeded
            pool_name: Name of the pool containing the proxy
        """
        pool = self.pools.get(pool_name, self.pools['default'])
        proxy = pool.get_proxy_by_url(proxy_url)

        if not proxy:
            # Try to find in default pool if not in specified pool
            if pool_name != 'default':
                proxy = self.pools['default'].get_proxy_by_url(proxy_url)

        if proxy:
            proxy.mark_success()
            logger.debug(f"Proxy success recorded: {proxy.label}")

    def mark_proxy_dead(self, proxy_url: str, pool_name: str = 'default') -> bool:
        """
        Explicitly mark a proxy as dead.

        Args:
            proxy_url: The URL of the proxy to mark as dead
            pool_name: Name of the pool containing the proxy

        Returns:
            True if proxy was found and marked dead, False otherwise
        """
        pool = self.pools.get(pool_name, self.pools['default'])
        proxy = pool.get_proxy_by_url(proxy_url)

        if not proxy:
            if pool_name != 'default':
                proxy = self.pools['default'].get_proxy_by_url(proxy_url)

        if proxy:
            proxy.mark_dead()
            return True

        logger.warning(f"Could not find proxy to mark as dead: {proxy_url}")
        return False

    def set_recovery_timeout(self, timeout_seconds: float, pool_name: str = None):
        """
        Set the recovery timeout for dead proxies.

        Args:
            timeout_seconds: Seconds after which dead proxies can be retried
            pool_name: Name of pool to set timeout for, or None for all pools
        """
        if pool_name:
            if pool_name in self.pools:
                self.pools[pool_name].recovery_timeout = timeout_seconds
        else:
            for pool in self.pools.values():
                pool.recovery_timeout = timeout_seconds

        logger.info(f"Set proxy recovery timeout to {timeout_seconds}s")

    def get_healthy_proxy_count(self, pool_name: str = 'default') -> int:
        """Get the number of healthy proxies in a pool."""
        pool = self.pools.get(pool_name, self.pools['default'])
        return pool.get_healthy_count()

    def get_dead_proxies(self, pool_name: str = 'default') -> list[str]:
        """Get list of dead proxy URLs in a pool."""
        pool = self.pools.get(pool_name, self.pools['default'])
        return [p.url for p in pool.proxies if p.health == ProxyHealth.DEAD]

    def revive_all_proxies(self, pool_name: str = None):
        """
        Reset all proxies to healthy status.

        Args:
            pool_name: Name of pool to revive, or None for all pools
        """
        pools_to_revive = [self.pools[pool_name]] if pool_name else self.pools.values()

        for pool in pools_to_revive:
            for proxy in pool.proxies:
                proxy.health = ProxyHealth.HEALTHY
                proxy.consecutive_failures = 0

        logger.info(f"Revived all proxies in {'all pools' if not pool_name else pool_name}")

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
