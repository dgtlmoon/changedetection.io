"""A group can choose the fetch method (browser) and the proxy for its watches.

For each of the two, the group says how its choice relates to the watch's own:

  'off'      - not used. The default, so a group changes nothing until it is switched on, and a browser or
               proxy can be set up on a group ahead of time and turned on when it is needed.
  'fallback' - used only when the watch has none of its own (left on the system default)
  'replace'  - used instead of the watch's own

Order: a 'replace' group, then the watch's own, then a 'fallback' group, then the system default. A watch in
several groups takes the first one that has a value, in the order of the watch's own group list, then the groups
that were applied by URL pattern.

This is core's own implementation of the fetch_route_alter hook, see pluggy_interface.resolve_fetch_route().
"""
import os
from typing import NamedTuple, Optional

from changedetectionio.plugin_api import hookimpl
from changedetectionio.strtobool import strtobool

GROUP_SETTING_MODE_OFF = 'off'
GROUP_SETTING_MODE_FALLBACK = 'fallback'
GROUP_SETTING_MODE_REPLACE = 'replace'

FETCH_BACKEND_GROUP_MODE_FIELD = 'fetch_backend_group_mode'
PROXY_GROUP_MODE_FIELD = 'proxy_group_mode'


class GroupChoice(NamedTuple):
    value: str
    group: dict
    # True when the group is used instead of the watch's own, so the watch's choice has no effect
    replaces_watch: bool


def is_fetch_backend_set(value):
    return bool(value) and value != 'system'


def is_proxy_set(value, proxy_list):
    """A proxy that exists, or 'no-proxy' where that is allowed. One that was removed counts as not set."""
    if value == 'no-proxy':
        return bool(strtobool(os.getenv('ENABLE_NO_PROXY_OPTION', 'True')))
    return bool(value) and value in (proxy_list or {})


def _group_choice(watch, datastore, field, mode_field, is_set) -> Optional[GroupChoice]:
    """The group that decides this setting for the watch, None when it stays the watch's own or the system's."""
    all_groups = datastore.data['settings']['application'].get('tags') or {}
    # Most installations have no group that is switched on, so look for those before any URL matching
    candidates = {
        uuid: group for uuid, group in all_groups.items()
        if group.get(mode_field) in (GROUP_SETTING_MODE_FALLBACK, GROUP_SETTING_MODE_REPLACE) and is_set(group.get(field))
    }
    if not candidates:
        return None

    assigned = watch.get('tags') or []
    watch_url = watch.get('url', '')
    groups = [candidates[uuid] for uuid in assigned if uuid in candidates]
    groups += [
        group for uuid, group in candidates.items()
        if uuid not in assigned and watch_url and group.matches_url(watch_url)
    ]

    for group in groups:
        if group.get(mode_field) == GROUP_SETTING_MODE_REPLACE:
            return GroupChoice(group.get(field), group, True)

    if groups and not is_set(watch.get(field)):
        return GroupChoice(groups[0].get(field), groups[0], False)

    return None


def _changed_by(choice: GroupChoice):
    return {
        'label': choice.group.get('title'),
        'group_uuid': choice.group.get('uuid'),
        'replaces_watch': choice.replaces_watch,
    }


@hookimpl
def fetch_route_alter(watch, datastore, route):
    choice = _group_choice(watch, datastore, 'fetch_backend', FETCH_BACKEND_GROUP_MODE_FIELD, is_fetch_backend_set)
    if choice:
        route['fetch_backend'] = choice.value
        route['changed_by']['fetch_backend'] = _changed_by(choice)

    proxy_list = getattr(datastore, 'proxy_list', None)
    choice = _group_choice(watch, datastore, 'proxy', PROXY_GROUP_MODE_FIELD, lambda value: is_proxy_set(value, proxy_list))
    if choice:
        route['proxy'] = choice.value
        route['changed_by']['proxy'] = _changed_by(choice)
