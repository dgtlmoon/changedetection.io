"""
Browser configs ("browser profiles") - named, engine-agnostic browser behaviour that a
watch can select (viewport / locale / timezone / asset-blocking ...).

Two layers live here:

  * FetcherConfig      - the behaviour schema. A watch resolves one of these (watch -> group
                         -> system default) and it is injected onto the content fetcher as
                         `.browser_config`; an updated fetcher applies the fields it can
                         honour and ignores the rest (capability-gated, e.g. block_* needs
                         FetcherCapabilities.supports_request_blocking). It is ALSO the on-disk
                         schema for each browsers.json entry.

  * BrowserConfigStore - persistence manager for browsers.json, mirroring proxies.json: an
                         optional file loaded lazily, with CRUD + a single default. Absent
                         file == no user configs == built-in default behaviour, so there is
                         nothing to create at startup.

browsers.json shape:
    { "<stable-id>": {"label": str, "base_fetcher": str, "is_default": bool,
                      "browser_config": { <FetcherConfig fields> }}, ... }

The id is a stable uuid assigned once (NOT a hash of the settings) so editing a config never
orphans the watches that reference it.
"""
import os
import uuid as uuid_builder
from os import path
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel, Field, field_validator

try:
    import orjson
    HAS_ORJSON = True
except ImportError:
    import json
    HAS_ORJSON = False


class BrowserConfigDoesntExist(Exception):
    """A watch/group references a browser config id that no longer exists in browsers.json."""
    def __init__(self, config_id, uuid=None):
        self.config_id = config_id
        self.uuid = uuid
        super().__init__(
            f"Browser config '{config_id}' no longer exists"
            f"{f' (watch {uuid})' if uuid else ''} - edit the watch/group and choose a browser."
        )


def _available_timezones():
    # Cached IANA tz set (zoneinfo builds it fresh each call, ~1ms).
    global _TZ_CACHE
    try:
        return _TZ_CACHE
    except NameError:
        from zoneinfo import available_timezones
        _TZ_CACHE = available_timezones()
        return _TZ_CACHE


class FetcherConfig(BaseModel):
    """Engine-agnostic per-instance browser behaviour.

    Unlike LLMSettings we deliberately do NOT use extra='forbid': this is a schema that gets
    written to disk (browsers.json) and backed up/restored across app versions, so it must
    tolerate version skew (a key removed in a future release should still load). There are no
    privileged fields here to protect against mass-assignment - everything is user-settable.
    Keep every field optional with a sensible default.
    """
    # Rendering / device
    viewport_width: Optional[int] = None       # px; None -> engine default
    viewport_height: Optional[int] = None
    # Identity / locale
    locale: Optional[str] = None               # e.g. 'de-DE' -> Accept-Language + navigator.language
    timezone_id: Optional[str] = None          # e.g. 'Europe/Berlin'
    # Screenshot
    screenshot_format: str = 'JPEG'
    # Cost / bandwidth - block assets (capability-gated by supports_request_blocking)
    block_resource_types: List[str] = Field(default_factory=list)  # e.g. ['image', 'font', 'media']
    block_url_patterns: List[str] = Field(default_factory=list)    # globs, e.g. ['*.ttf', '*/analytics/*']
    # Local-launch engines only (capability-gated by supports_browser_type)
    browser_type: Optional[str] = None         # 'chromium' | 'firefox' | 'webkit'
    # Delete the per-fetch temp profile after use (capability-gated by supports_delete_created_files)
    delete_created_files: bool = True
    # timeout: plain HTTP client only (capability-gated by supports_request_timeout).
    timeout: Optional[int] = None              # request timeout in seconds; None -> global default
    # user_agent: honoured by every engine (capability supports_custom_user_agent) via the
    # request_headers User-Agent channel.
    user_agent: Optional[str] = None           # overrides the User-Agent header for this profile

    @field_validator('timeout')
    @classmethod
    def _validate_timeout(cls, v):
        if v is not None and not (1 <= v <= 999):
            raise ValueError("Timeout must be between 1 and 999 seconds")
        return v

    def apply_user_agent(self, request_headers):
        """Set this profile's User-Agent on request_headers (the channel every fetcher - plain
        client and browsers - uses), if configured. Applied early (before a watch's own headers)
        so an explicit per-watch User-Agent still wins. Works for dict / CaseInsensitiveDict.
        A None user_agent is a no-op. Returns request_headers for chaining."""
        if self.user_agent:
            for k in [k for k in list(request_headers.keys()) if k.lower() == 'user-agent']:
                del request_headers[k]
            request_headers['User-Agent'] = self.user_agent
        return request_headers

    def effective_timeout(self, default):
        """This profile's request timeout, else the caller's default (plain HTTP client only)."""
        return self.timeout or default

    @field_validator('browser_type')
    @classmethod
    def _validate_browser_type(cls, v):
        if v and v not in ('chromium', 'firefox', 'webkit'):
            raise ValueError(f"Unknown browser_type '{v}' - use chromium, firefox or webkit")
        return v

    @field_validator('locale')
    @classmethod
    def _validate_locale(cls, v):
        """BCP-47 tag validated against babel's CLDR data (e.g. 'de-DE', 'en-GB')."""
        if not v:
            return v
        from babel import Locale, UnknownLocaleError
        try:
            Locale.parse(v.strip(), sep='-')
        except (UnknownLocaleError, ValueError):
            raise ValueError(f"Unknown locale '{v}' - use a BCP-47 tag like 'de-DE' or 'en-GB'")
        return v.strip()

    @field_validator('timezone_id')
    @classmethod
    def _validate_timezone(cls, v):
        """IANA timezone name validated against the stdlib zoneinfo database."""
        if not v:
            return v
        if v.strip() not in _available_timezones():
            raise ValueError(f"Unknown IANA timezone '{v}' - e.g. 'Europe/Berlin', 'UTC'")
        return v.strip()


class BrowserConfigEntry(BaseModel):
    """One browsers.json entry (the id is the dict key, not stored in the entry).

    Note: there is deliberately no `is_default` here. The default browser is the global
    settings.application.fetch_backend (a single source of truth that can point at a built-in
    engine OR a browser-config id), so it doesn't live per-entry - see
    ChangeDetectionStore.get_default_backend() / Watch.get_fetch_backend.
    """
    label: str = ''
    base_fetcher: str = 'html_webdriver'
    browser_config: FetcherConfig = Field(default_factory=FetcherConfig)


class BrowserConfigStore:
    """Persistence manager for browsers.json. Thin, self-contained, backup-friendly."""

    def __init__(self, datastore_path, lock):
        self._path = os.path.join(datastore_path, 'browsers.json')
        self._lock = lock
        # mtime-keyed cache of the parsed file. all()/get() are hit per-watch on every watchlist
        # render + fetch resolution, so re-reading + re-parsing browsers.json each time is real
        # amplification (cf. the favicon-glob fix). Cache the parsed dict and only re-read when
        # the file's mtime changes - picks up edits (save bumps mtime) without staleness.
        self._cache = None
        self._cache_mtime = None

    # ---- low level load/save ----
    def all(self):
        """Raw dict {id: entry-dict}. Empty dict when the file is absent. mtime-cached."""
        try:
            mtime = os.path.getmtime(self._path)
        except OSError:
            # File absent (or unreadable) - nothing configured yet.
            self._cache, self._cache_mtime = {}, None
            return {}
        if self._cache is not None and self._cache_mtime == mtime:
            return self._cache
        try:
            if HAS_ORJSON:
                with open(self._path, 'rb') as f:
                    data = orjson.loads(f.read()) or {}
            else:
                with open(self._path, encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception as e:
            logger.error(f"Could not load browsers.json: {e}")
            return {}
        self._cache, self._cache_mtime = data, mtime
        return data

    def _save(self, configs):
        # Deferred import avoids a model -> store import cycle at module load.
        from changedetectionio.store.file_saving_datastore import save_json_atomic
        with self._lock:
            save_json_atomic(self._path, configs, label="browsers")
        # Invalidate so the next all()/get() re-reads (its mtime will differ anyway).
        self._cache, self._cache_mtime = None, None

    # ---- CRUD ----
    def get(self, config_id):
        return self.all().get(config_id)

    def add(self, label, base_fetcher, browser_config=None):
        """Create a config; returns its stable id."""
        configs = self.all()
        new_id = str(uuid_builder.uuid4())
        configs[new_id] = BrowserConfigEntry(
            label=label,
            base_fetcher=base_fetcher,
            browser_config=FetcherConfig(**(browser_config or {})),
        ).model_dump()
        self._save(configs)
        return new_id

    def upsert(self, config_id, label, base_fetcher, browser_config=None):
        """Create-or-replace an entry at a specific key. Used for built-in engine configs,
        which are keyed by the engine name (e.g. 'html_webdriver') rather than a uuid."""
        configs = self.all()
        configs[config_id] = BrowserConfigEntry(
            label=label,
            base_fetcher=base_fetcher,
            browser_config=FetcherConfig(**(browser_config or {})),
        ).model_dump()
        self._save(configs)
        return config_id

    def update(self, config_id, label=None, base_fetcher=None, browser_config=None):
        configs = self.all()
        raw = configs.get(config_id)
        if not raw:
            return False
        entry = BrowserConfigEntry(**raw)
        if label is not None:
            entry.label = label
        if base_fetcher is not None:
            entry.base_fetcher = base_fetcher
        if browser_config is not None:
            entry.browser_config = FetcherConfig(**browser_config)
        configs[config_id] = entry.model_dump()
        self._save(configs)
        return True

    def delete(self, config_id):
        configs = self.all()
        if config_id in configs:
            del configs[config_id]
            self._save(configs)
            return True
        return False

    def resolve_config(self, config_id):
        """Validated FetcherConfig for an id, or None if the id is unknown."""
        raw = self.get(config_id)
        if not raw:
            return None
        return FetcherConfig(**(raw.get('browser_config') or {}))

    def engine_and_config(self, selected):
        """Map an already-resolved selector to (entry, engine_name, FetcherConfig).

        The single place the trio of resolvers (content fetcher, watchlist status icon,
        capability checks) turns a selector into its engine + behaviour:
          - a stored browser config -> (entry, its base_fetcher, its FetcherConfig)
          - a built-in engine name  -> (None, that name, empty FetcherConfig)
        `entry is None` also tells the caller the selector wasn't a saved config (so it can do
        the built-in / extra_browser / dangling-id handling).
        """
        entry = self.get(selected) if selected else None
        if entry:
            return entry, (entry.get('base_fetcher') or 'html_webdriver'), FetcherConfig(**(entry.get('browser_config') or {}))
        return None, selected, FetcherConfig()


# One BrowserConfigStore instance per datastore path, so the mtime cache is shared by everything
# reading browsers.json (the ChangeDetectionStore and every Watch, which only holds the data dict
# + its path). The ChangeDetectionStore registers its own (lock-bearing) instance here so writes
# and the watch-side reads go through the same cache.
_STORE_REGISTRY = {}


def register_browser_config_store(datastore_path, store):
    _STORE_REGISTRY[datastore_path] = store


def get_browser_config_store(datastore_path):
    """The shared BrowserConfigStore for a datastore path (created read-only if none registered)."""
    store = _STORE_REGISTRY.get(datastore_path)
    if store is None:
        store = BrowserConfigStore(datastore_path, lock=None)
        _STORE_REGISTRY[datastore_path] = store
    return store


def list_builtin_browsers():
    """Built-in engine 'browsers' - always present, zero-override config.

    These are the engines the app instantiated at boot (available_fetchers() already reflects
    the env-driven html_webdriver -> playwright/puppeteer/selenium choice), exposed as
    selectable browsers with a stable id == the engine name. That id equals the value existing
    watches already store in fetch_backend, so nothing breaks and they always show in the list.
    """
    from changedetectionio import content_fetchers
    out = []
    for name, description in content_fetchers.available_fetchers():
        cls = getattr(content_fetchers, name, None)
        # Skip "base only" engines (e.g. html_playwright_builtin) - they aren't usable directly,
        # only as the base of a browser config (chosen in the Add Browser form).
        if cls is not None and not getattr(cls, 'ready_to_use', True):
            continue
        out.append({'id': name, 'label': description, 'base_fetcher': name})
    return out


def list_watch_browser_choices(datastore):
    """(value, label) choices for the watch-level 'Browser' picker:
    system default, the always-present built-in engine browsers, then the user's saved browsers.
    """
    choices = [('system', _system_default_label(datastore))]
    for b in list_builtin_browsers():
        choices.append((b['id'], b['label']))
    for cid, entry in datastore.browser_config_store.all().items():
        choices.append((cid, entry.get('label') or cid))
    return choices


def _system_default_label(datastore):
    from flask_babel import gettext
    return gettext('Default (system settings)')


# --- Thin free-function delegators --------------------------------------------------------
# The resolution chain (PDF / group override / watch / 'system' -> global default) lives on the
# Watch model now (Watch.get_fetch_backend & friends) - only watches fetch, so the watch owns
# "what do I fetch with?". These wrappers keep the historical (watch, datastore) call shape for
# templates/blueprints/tests; `datastore` is accepted but unused (the Watch self-resolves).

def resolve_watch_fetcher_engine(watch, datastore=None):
    """The concrete engine name that will actually fetch this watch. See Watch.resolved_fetch_engine."""
    return watch.resolved_fetch_engine


def resolve_browser_config_override(watch, datastore=None):
    """If a group/tag overrides this watch's browser config, describe it, else None.
    See Watch.browser_config_override."""
    return watch.browser_config_override


def resolve_watch_browser_display(watch, datastore=None):
    """Display info for the watchlist status icon: which browser a watch effectively uses.

    Returns dict: {engine, browser_type, label, is_named, group_title} where `label` is the
    named browser-config's label (or the built-in engine description), `browser_type` is the
    resolved sub-engine (firefox/chromium/webkit) if set, and `group_title` is set when a group
    override supplies it.
    """
    from changedetectionio import content_fetchers
    store = watch.browser_config_store
    override = watch.browser_config_override

    entry, engine, cfg = store.engine_and_config(watch.get_fetch_backend)
    if entry:
        label = entry.get('label')
    else:
        label = dict(content_fetchers.available_fetchers()).get(engine, engine)

    return {
        'engine': engine,
        'browser_type': cfg.browser_type,
        'label': label,
        'is_named': entry is not None,
        'group_title': override['group_title'] if override else None,
    }
