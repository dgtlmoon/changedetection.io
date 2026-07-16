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
    application `fetch_backend` (a single source of truth that can point at a built-in engine
    OR a browser-config id), so it doesn't live per-entry - see base_fetcher_for().
    """
    label: str = ''
    base_fetcher: str = 'html_webdriver'
    browser_config: FetcherConfig = Field(default_factory=FetcherConfig)


class BrowserConfigStore:
    """Persistence manager for browsers.json. Thin, self-contained, backup-friendly."""

    def __init__(self, datastore_path, lock):
        self._path = os.path.join(datastore_path, 'browsers.json')
        self._lock = lock

    # ---- low level load/save ----
    def all(self):
        """Raw dict {id: entry-dict}. Empty dict when the file is absent."""
        if not path.isfile(self._path):
            return {}
        try:
            if HAS_ORJSON:
                with open(self._path, 'rb') as f:
                    return orjson.loads(f.read()) or {}
            with open(self._path, encoding='utf-8') as f:
                return json.load(f) or {}
        except Exception as e:
            logger.error(f"Could not load browsers.json: {e}")
            return {}

    def _save(self, configs):
        # Deferred import avoids a model -> store import cycle at module load.
        from changedetectionio.store.file_saving_datastore import save_json_atomic
        with self._lock:
            save_json_atomic(self._path, configs, label="browsers")

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


def base_fetcher_for(value, datastore):
    """Map any fetch_backend value to the concrete engine/fetcher name.

    Accepts a user browser-config id, a built-in engine name ('html_requests'/'html_webdriver'/
    'extra_browser_*'), or the sentinel 'system'. This is the single place the rest of the
    codebase should go through when it needs the *engine* behind a watch/global fetch_backend
    (capability checks, screenshot support, etc.). 'system' resolves to the global default,
    which may itself be a browser-config id.
    """
    # `datastore` may be the ChangeDetectionStore (has .browser_config_store and .data) or the
    # raw settings data dict (Watch._datastore). Tolerate both; browser-config lookups are only
    # possible when the store object is available.
    store = getattr(datastore, 'browser_config_store', None)
    data = getattr(datastore, 'data', datastore)
    entry = store.get(value) if (store and value) else None
    if entry:
        return entry.get('base_fetcher') or 'html_webdriver'
    if not value or value == 'system':
        gd = data['settings']['application'].get('fetch_backend', 'html_requests')
        gd_entry = store.get(gd) if (store and gd) else None
        return (gd_entry.get('base_fetcher') if gd_entry else gd) or 'html_requests'
    return value


def list_builtin_browsers():
    """Built-in engine 'browsers' - always present, zero-override config.

    These are the engines the app instantiated at boot (available_fetchers() already reflects
    the env-driven html_webdriver -> playwright/puppeteer/selenium choice), exposed as
    selectable browsers with a stable id == the engine name. That id equals the value existing
    watches already store in fetch_backend, so nothing breaks and they always show in the list.
    """
    from changedetectionio import content_fetchers
    return [{'id': name, 'label': description, 'base_fetcher': name}
            for name, description in content_fetchers.available_fetchers()]


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


def resolve_browser_config_override(watch, datastore):
    """If a group/tag overrides this watch's browser config, describe it, else None.

    Uses the group's own dedicated enabler (browser_config_overrides_watch), NOT the coarse
    legacy `overrides_watch` flag. Tags are checked in the watch's tag-list order; the first
    one whose enabler is on and whose selected config still exists wins (deterministic).

    Returns: {group_uuid, group_title, config_id, label} or None.
    """
    tags = datastore.data['settings']['application'].get('tags', {})
    builtins = {b['id']: b for b in list_builtin_browsers()}
    for tag_uuid in (watch.get('tags') or []):
        tag = tags.get(tag_uuid)
        if not tag:
            continue
        if tag.get('browser_config_overrides_watch') and tag.get('browser_config'):
            cid = tag.get('browser_config')
            entry = datastore.browser_config_store.get(cid)
            # The override may point at a user browser (uuid) OR a built-in engine (id == name).
            if entry:
                label = entry.get('label')
            elif cid in builtins:
                label = builtins[cid]['label']
            else:
                continue  # dangling / unknown - don't apply
            return {
                'group_uuid': tag_uuid,
                'group_title': tag.get('title'),
                'config_id': cid,
                'label': label,
            }
    return None
