"""Plugin settings on the watch, group and system settings pages, plus the helpers plugins use with them.

  - hook settings_form_section(scope) -> SettingsSection: a plugin adds a WTForms form to the watch
    edit page (scope 'watch', Request tab), the group edit page ('tag', Browser tab) or Settings
    ('global', Fetching tab). Saved as plugin_settings[<plugin_id>] on the watch, on the group, or
    in the system settings.
  - resolved_plugin_settings(watch, plugin_id): the combined settings, field by field - the watch's
    own value, else the first of its groups that has one, else the system settings. A value of
    INHERIT ('' or None) means "not set here".
  - get/set/clear_plugin_state(): small runtime state a plugin keeps on a watch (watch.json
    plugin_state[<plugin_id>]), apart from the user's settings so saving the form never wipes it.
  - queue_recheck(uuid): check a watch again soon.
  - hook fetch_engine_override(watch, engine): fetch a watch with another engine, applied both when
    fetching and when working out what the watch's browser can do.
  - hook watch_list_extra_text(watch): short notes under the watch in the watch list.

Plugins use these through changedetectionio.plugin_api.
"""
from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

SCOPES = ('watch', 'tag', 'global')
INHERIT = ('', None)


@dataclass
class SettingsSection:
    """A plugin's part of the watch, group or system settings page.

    plugin_id:   lowercase letters, digits and underscores; also the key its settings are stored under
    label:       heading of the section
    form_class:  a wtforms.Form subclass; its validators run when the page is saved. For the watch and
                 group scopes, give fields an "inherit" choice whose value is '' so the next level decides
    template:    optional Jinja2 template name rendered instead of the default field list; it gets
                 `section` and `subform`
    description: optional text shown under the heading
    """
    plugin_id: str
    label: Any
    form_class: Any
    template: Optional[str] = None
    description: Any = None

    @property
    def field_name(self):
        return f"plugin_{self.plugin_id}"


def get_settings_sections(scope):
    """Every plugin section for a settings page, in registration order, invalid ones logged and dropped."""
    from wtforms import Form
    from changedetectionio.browser_lifecycle import PLUGIN_ID_PATTERN
    from changedetectionio.pluggy_interface import plugin_manager

    sections, seen = [], set()
    for section in reversed(plugin_manager.hook.settings_form_section(scope=scope)):
        if section is None:
            continue
        if not isinstance(section, SettingsSection):
            logger.error(f"settings_form_section must return a SettingsSection, got {type(section).__name__}")
            continue
        if not PLUGIN_ID_PATTERN.match(section.plugin_id or ''):
            logger.error(f"Invalid plugin_id {section.plugin_id!r} for a settings section")
            continue
        if not (isinstance(section.form_class, type) and issubclass(section.form_class, Form)):
            logger.error(f"Settings section '{section.plugin_id}' form_class must be a wtforms.Form subclass")
            continue
        if section.plugin_id in seen:
            continue
        seen.add(section.plugin_id)
        sections.append(section)
    return sections


def form_class_with_sections(base_form_class, sections):
    """`base_form_class` with each section's form attached as a FormField (WTForms only binds fields
    when a class is created, so this builds a subclass)."""
    if not sections:
        return base_form_class
    from wtforms import FormField
    attrs = {section.field_name: FormField(section.form_class, label=section.label) for section in sections}
    return type(f"{base_form_class.__name__}WithPluginSettings", (base_form_class,), attrs)


def form_data_with_sections(data, sections, stored):
    """A copy of `data` for the form, with each section's saved settings (from `stored`, the
    plugin_settings dict of the watch / group / system) under its sub-form's name."""
    data = dict(data or {})
    stored = stored or {}
    for section in sections:
        data[section.field_name] = dict(stored.get(section.plugin_id) or {})
    return data


def save_sections(form, sections, target):
    """Store each section's submitted settings in target['plugin_settings'] (target: the watch, the
    group, or the system settings dict) and drop the sub-form values that a blanket
    `target.update(form.data)` put next to them. Settings of plugins that offered no section this
    time are kept. Returns an error message, or None when saved."""
    from changedetectionio.browser_lifecycle import section_settings_error
    plugin_settings = dict(target.get('plugin_settings') or {})
    for section in sections:
        data = getattr(form, section.field_name).data
        problem = section_settings_error(data)
        if problem:
            return f"{section.label}: {problem}"
        plugin_settings[section.plugin_id] = data
    for section in sections:
        target.pop(section.field_name, None)
    if sections:
        target['plugin_settings'] = plugin_settings
    return None


def _app_settings(watch):
    datastore = getattr(watch, '_datastore', None)
    if not datastore:
        return {}
    try:
        return datastore['settings']['application']
    except (KeyError, TypeError):
        return {}


def resolved_plugin_settings(watch, plugin_id):
    """`plugin_id`'s settings for this watch, field by field: the watch's own value, else the first
    of its groups (in the watch's order) with a value, else the system settings. INHERIT values ('',
    None) count as "not set". Cheap - reads dicts only."""
    app = _app_settings(watch)
    levels = [(watch.get('plugin_settings') or {}).get(plugin_id) or {}]
    tags = app.get('tags') or {}
    for tag_uuid in watch.get('tags') or []:
        tag = tags.get(tag_uuid)
        if tag:
            levels.append((tag.get('plugin_settings') or {}).get(plugin_id) or {})
    levels.append((app.get('plugin_settings') or {}).get(plugin_id) or {})

    resolved = {}
    for level in reversed(levels):           # system first, the watch's own value last (wins)
        for key, value in level.items():
            if value not in INHERIT:
                resolved[key] = value
    return resolved


def get_plugin_state(watch, plugin_id):
    """The runtime state a plugin keeps on this watch (a copy), {} when none."""
    return dict((watch.get('plugin_state') or {}).get(plugin_id) or {})


def _stored_watch(watch):
    """The watch as stored in the datastore. Hooks are often handed a copy (a check works on a
    deepcopy of the watch), and state written only to a copy would be lost."""
    datastore = getattr(watch, '_datastore', None)
    try:
        stored = datastore['watching'].get(watch.get('uuid')) if datastore else None
    except (KeyError, TypeError, AttributeError):
        stored = None
    return stored if stored is not None else watch


def set_plugin_state(watch, plugin_id, **values):
    """Merge `values` into the plugin's state on this watch and save it (on the stored watch, and on
    `watch` too when that's a copy)."""
    stored = _stored_watch(watch)
    state = dict(stored.get('plugin_state') or {})
    state[plugin_id] = {**(state.get(plugin_id) or {}), **values}
    stored['plugin_state'] = state
    if stored is not watch:
        watch['plugin_state'] = dict(state)
    _commit(stored)


def clear_plugin_state(watch, plugin_id):
    """Remove the plugin's state from this watch (no-op when there is none)."""
    stored = _stored_watch(watch)
    for target in {id(stored): stored, id(watch): watch}.values():
        state = dict(target.get('plugin_state') or {})
        if plugin_id in state:
            del state[plugin_id]
            target['plugin_state'] = state
    _commit(stored)


def _commit(watch):
    commit = getattr(watch, 'commit', None)
    if callable(commit):
        try:
            commit()
        except Exception as e:
            logger.error(f"Could not save plugin state for watch {watch.get('uuid')}: {e}")


# Last plugin-requested re-check per watch, so a plugin mistake can't turn into a check storm
_RECHECK_MIN_SECONDS = 60
_last_rechecks = {}


def queue_recheck(uuid):
    """Check this watch again as soon as a worker is free. At most once a minute per watch; returns
    False when it was refused for that reason."""
    import time
    from changedetectionio import queuedWatchMetaData, worker_pool
    from changedetectionio.flask_app import update_q
    now = time.time()
    if now - _last_rechecks.get(uuid, 0) < _RECHECK_MIN_SECONDS:
        logger.warning(f"Not re-queueing watch {uuid} again so soon (plugin request within {_RECHECK_MIN_SECONDS}s)")
        return False
    _last_rechecks[uuid] = now
    worker_pool.queue_item_async_safe(update_q, queuedWatchMetaData.PrioritizedItem(priority=1, item={'uuid': uuid}))
    return True


def apply_fetch_engine_override(watch, engine):
    """The engine to really fetch `watch` with: a plugin's fetch_engine_override(), when it names a
    registered engine, else `engine`."""
    from changedetectionio import content_fetchers
    from changedetectionio.pluggy_interface import plugin_manager
    try:
        override = plugin_manager.hook.fetch_engine_override(watch=watch, engine=engine)
    except Exception as e:
        logger.error(f"fetch_engine_override failed: {e}")
        return engine
    if override and override != engine:
        if getattr(content_fetchers, override, None) is None:
            logger.error(f"fetch_engine_override returned unknown engine '{override}', ignoring it")
            return engine
        return override
    return engine


def collect_watch_list_extra_text(watch):
    """All plugins' notes for this watch in the watch list, as a list of strings."""
    from changedetectionio.pluggy_interface import plugin_manager
    notes = []
    try:
        for result in reversed(plugin_manager.hook.watch_list_extra_text(watch=watch)):
            if not result:
                continue
            notes.extend([result] if isinstance(result, str) else [str(r) for r in result if r])
    except Exception as e:
        logger.error(f"watch_list_extra_text failed: {e}")
    return notes
