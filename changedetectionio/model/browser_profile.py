"""
BrowserProfile — named, reusable browser/fetcher configuration.

Storage key
-----------
Profiles are stored in ``settings.application.browser_profiles`` as a plain dict
keyed by *machine name* — a lowercase, underscore-separated slug derived from the
human-readable ``name`` field:

    'My Blocking Chrome'        →  'my_blocking_chrome'
    'Custom CDP — Mobile (375px)' →  'custom_cdp_mobile_375px'

Using the machine name as the key means that deleting a profile and recreating
it with the same name restores the original key, so all watches that referenced
it continue to work without any manual re-linking.

Resolution chain
----------------
``resolve_browser_profile(watch, datastore)`` walks:

    watch.browser_profile  →  first tag with overrides_watch=True  →
    settings.application.browser_profile  →  built-in fallback

It never raises.  Stale / missing machine-name references are logged and the
resolver falls through to the next level.

Built-in profiles
-----------------
``BUILTIN_REQUESTS`` and ``BUILTIN_BROWSER`` are always available and cannot be
deleted from the UI (``is_builtin=True``).  Their machine names are stored in
``RESERVED_MACHINE_NAMES`` to block user profiles from shadowing them.

Migration
---------
``store/updates.py::update_31`` converts the legacy ``fetch_backend`` field on
watches, tags and global settings into ``browser_profile`` machine-name
references.  After that migration no legacy paths are needed here.
"""

from __future__ import annotations

import re
from typing import Optional

from loguru import logger
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NAME_MAX_LEN = 100


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class BrowserProfile(BaseModel):
    """
    A named, reusable configuration for how a watch fetches its target URL.

    The *machine name* (see ``get_machine_name()``) is the stable storage key.
    Updating ``name`` changes the machine name; any watch that referenced the
    old machine name will then fall back through the resolution chain until it
    is explicitly re-pointed.  To replace a profile without breaking watches,
    delete it and recreate it with the *same* name.
    """

    name: str
    """Human-readable label shown in the UI.  Max 100 characters."""

    fetch_backend: str = 'requests'
    """
    Which fetch engine to use.  This is the *clean* fetcher name without the
    ``html_`` module prefix (e.g. ``'requests'``, ``'webdriver'``,
    ``'playwright'``, ``'puppeteer'``, ``'cloakbrowser'``).

    The module-level ``html_`` prefix (``html_requests``, ``html_webdriver``,
    …) is an implementation detail of ``content_fetchers/``.  Use
    ``get_fetcher_class_name()`` to obtain the full module attribute name when
    you need to look up the class.

    Must be non-empty and contain only ``[a-z0-9_]`` characters.
    """

    is_builtin: bool = False
    """Built-in profiles are always present and cannot be deleted from the UI."""

    # ------------------------------------------------------------------
    # Browser-specific settings (silently ignored by html_requests)
    # ------------------------------------------------------------------

    browser_connection_url: Optional[str] = None
    """
    Custom CDP / WebSocket endpoint, e.g. ``ws://my-chrome:3000``.
    Overrides the system-wide ``PLAYWRIGHT_DRIVER_URL`` for this profile.
    Only meaningful for ``html_webdriver`` profiles.
    """

    viewport_width: int = 1280
    """
    Browser viewport width in pixels.
    Common presets: 375 (iPhone), 768 (tablet), 1280 (desktop).
    """

    viewport_height: int = 1000
    """
    Browser viewport height in pixels.
    Common presets: 812 (iPhone), 1024 (tablet), 1000 (desktop).
    """

    block_images: bool = False
    """
    Block all image requests.  Typically cuts page-load time by 40-70 % on
    image-heavy sites with no impact on text-based change detection.
    """

    block_fonts: bool = False
    """Block web-font requests.  Modest speed gain; rarely affects detection."""

    user_agent: Optional[str] = None
    """
    Override the browser User-Agent string.
    ``None`` keeps the fetcher's built-in default, which already strips
    obvious headless markers such as ``HeadlessChrome``.
    """

    ignore_https_errors: bool = False
    """
    Proceed even when the server's TLS certificate is invalid or self-signed.
    Useful for staging / development environments.
    """

    locale: Optional[str] = None
    """
    Browser locale (e.g. ``en-US``, ``de-DE``).
    Sets the ``Accept-Language`` header and ``navigator.language``.
    Some sites serve different prices or copy based on locale.
    """

    model_config = {"frozen": False}

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator('fetch_backend')
    @classmethod
    def _validate_fetch_backend(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('fetch_backend cannot be empty')
        if not re.fullmatch(r'[a-z0-9_]+', v):
            raise ValueError(
                f"fetch_backend must contain only lowercase letters, digits and underscores, got {v!r}"
            )
        if v.startswith('html_'):
            raise ValueError(
                f"fetch_backend should be the clean fetcher name without the 'html_' prefix "
                f"(e.g. 'requests', 'webdriver', 'playwright'). Got {v!r}. "
                f"Use get_fetcher_class_name() to obtain the full module attribute name."
            )
        return v

    @field_validator('name')
    @classmethod
    def _validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('Name cannot be empty')
        if len(v) > NAME_MAX_LEN:
            raise ValueError(f'Name must be {NAME_MAX_LEN} characters or less')
        return v

    # ------------------------------------------------------------------
    # Machine-name helpers
    # ------------------------------------------------------------------

    @staticmethod
    def machine_name_from_str(name: str) -> str:
        """
        Convert a human name to a machine-safe storage key.

        Transformation rules (applied in order):

        1. Strip surrounding whitespace; lower-case.
        2. Replace runs of whitespace or hyphens with a single ``_``.
        3. Drop every character that is not ``[a-z0-9_]``.
        4. Collapse consecutive underscores.
        5. Strip leading / trailing underscores.
        6. Truncate to ``NAME_MAX_LEN`` characters.

        Examples::

            'My Blocking Browser Chrome'  →  'my_blocking_browser_chrome'
            'Custom CDP — Mobile (375px)' →  'custom_cdp_mobile_375px'
            '  Weird   ---   Name  '      →  'weird_name'
        """
        s = name.strip().lower()
        s = re.sub(r'[\s\-]+', '_', s)    # whitespace / hyphens → underscore
        s = re.sub(r'[^a-z0-9_]', '', s)  # drop everything else
        s = re.sub(r'_+', '_', s)         # collapse repeated underscores
        s = s.strip('_')                   # drop leading / trailing underscores
        return s[:NAME_MAX_LEN]

    def get_machine_name(self) -> str:
        """Return the machine-safe storage key derived from this profile's ``name``."""
        return self.machine_name_from_str(self.name)

    def get_fetcher_class_name(self) -> str:
        """Return the clean fetcher name for this profile (same as ``fetch_backend``).

        Use with ``content_fetchers.get_fetcher()``::

            from changedetectionio import content_fetchers
            fetcher_cls = content_fetchers.get_fetcher(profile.get_fetcher_class_name())
        """
        return self.fetch_backend


# ---------------------------------------------------------------------------
# Built-in profiles (always present, cannot be deleted)
# ---------------------------------------------------------------------------

BUILTIN_REQUESTS = BrowserProfile(
    name='Direct HTTP (requests)',
    fetch_backend='requests',
    is_builtin=True,
)

BUILTIN_PLAYWRIGHT = BrowserProfile(
    name='Browser (Chrome/Playwright)',
    fetch_backend='playwright',
    is_builtin=True,
)

BUILTIN_SELENIUM = BrowserProfile(
    name='Browser (Chrome/Selenium)',
    fetch_backend='selenium',
    is_builtin=True,
)

BUILTIN_PUPPETEER = BrowserProfile(
    name='Browser (Chrome/Puppeteer)',
    fetch_backend='puppeteer',
    is_builtin=True,
)

# Backwards-compatible alias — code that imported BUILTIN_BROWSER keeps working.
BUILTIN_BROWSER = BUILTIN_PLAYWRIGHT

# Keyed by machine name for O(1) lookup.
_BUILTINS: dict[str, BrowserProfile] = {
    b.get_machine_name(): b
    for b in (BUILTIN_REQUESTS, BUILTIN_PLAYWRIGHT, BUILTIN_SELENIUM, BUILTIN_PUPPETEER)
}

# Machine names that cannot be used by user-created profiles.
RESERVED_MACHINE_NAMES: frozenset[str] = frozenset(_BUILTINS.keys())


def get_default_browser_builtin() -> BrowserProfile:
    """Return the built-in browser profile that matches the current environment.

    Reads the same env vars as ``content_fetchers.get_active_browser_fetcher_name()``:

    * ``PLAYWRIGHT_DRIVER_URL`` set + ``FAST_PUPPETEER_CHROME_FETCHER=False`` → Playwright
    * ``PLAYWRIGHT_DRIVER_URL`` set + ``FAST_PUPPETEER_CHROME_FETCHER=True``  → Puppeteer
    * Neither set → Selenium
    """
    import os
    from changedetectionio.strtobool import strtobool
    if os.getenv('PLAYWRIGHT_DRIVER_URL', False):
        if not strtobool(os.getenv('FAST_PUPPETEER_CHROME_FETCHER', 'False')):
            return BUILTIN_PLAYWRIGHT
        return BUILTIN_PUPPETEER
    return BUILTIN_SELENIUM


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def get_builtin_profiles() -> dict[str, BrowserProfile]:
    """Return a shallow copy of the built-in profiles dict (keyed by machine name)."""
    return dict(_BUILTINS)


def get_profile(machine_name: str, store_profiles: dict) -> Optional[BrowserProfile]:
    """
    Look up a ``BrowserProfile`` by machine name.

    Built-ins are checked first and cannot be shadowed by user profiles.
    Returns ``None`` when the machine name is unknown or the stored data is
    corrupt (a warning is logged in the latter case).
    """
    if machine_name in _BUILTINS:
        return _BUILTINS[machine_name]

    raw = store_profiles.get(machine_name)
    if raw is None:
        return None

    if isinstance(raw, BrowserProfile):
        return raw

    try:
        return BrowserProfile(**raw)
    except Exception as exc:
        logger.warning(f"BrowserProfile '{machine_name}': failed to deserialize — {exc}")
        return None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def resolve_browser_profile(watch, datastore) -> BrowserProfile:
    """
    Resolve the effective ``BrowserProfile`` for *watch*.

    Resolution chain
    ~~~~~~~~~~~~~~~~
    1. ``watch['browser_profile']`` — explicit machine name set on the watch.
    2. First tag with ``overrides_watch=True`` that has ``browser_profile`` set.
    3. ``settings.application['browser_profile']`` — system-wide default.
    4. Built-in fallback: ``BUILTIN_REQUESTS`` (requests is always the safe default).

    Never raises.  A stale / missing machine-name reference produces a
    ``logger.warning`` and the resolver continues down the chain.
    """
    from changedetectionio.model.resolver import resolve_setting

    store_profiles: dict = datastore.data['settings']['application'].get('browser_profiles', {})

    machine_name = resolve_setting(
        watch, datastore,
        field_name='browser_profile',
        sentinel_values={'system', 'default', ''},
        default=None,
        require_tag_override=True,
    )

    if machine_name:
        profile = get_profile(machine_name, store_profiles)
        if profile:
            return profile
        logger.warning(
            f"Watch {watch.get('uuid')!r}: browser_profile {machine_name!r} not found, "
            f"falling back through the chain"
        )

    return BUILTIN_REQUESTS
