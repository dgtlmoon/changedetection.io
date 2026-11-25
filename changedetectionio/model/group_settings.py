"""A group can choose the fetch method (browser), the proxy and the recheck time for its watches.

For each of them, the group says how its choice relates to the watch's own:

  'off'      - not used. The default, so a group changes nothing until it is switched on, and a browser or
               proxy can be set up on a group ahead of time and turned on when it is needed.
  'fallback' - used only when the watch has none of its own (left on the system default)
  'replace'  - used instead of the watch's own

Order: a 'replace' group, then the watch's own, then a 'fallback' group, then the system default. A watch in
several groups takes the first one that has a value, in the order of the watch's own group list, then the groups
that were applied by URL pattern.

Fetch method and proxy are core's own implementation of the fetch_route_alter hook, see
pluggy_interface.resolve_fetch_route(). The recheck time is read directly by the scheduler, which asks for every
watch on every pass, see groups_with_recheck_time() and recheck_time_group_choice().
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
# One mode for the interval and the time schedule together, a watch also has one switch for both
RECHECK_TIME_GROUP_MODE_FIELD = 'time_between_check_group_mode'


class GroupChoice(NamedTuple):
    value: object
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


class SwitchedOnGroups(NamedTuple):
    by_uuid: dict
    # The ones that also apply to watches by URL pattern, so only those are matched against each watch's URL
    with_url_pattern: list


def _switched_on_groups(datastore, mode_field, has_value) -> Optional[SwitchedOnGroups]:
    """The groups that are switched on for this setting and have something to give, None when there are none."""
    all_groups = datastore.data['settings']['application'].get('tags') or {}
    by_uuid = {
        uuid: group for uuid, group in all_groups.items()
        if group.get(mode_field) in (GROUP_SETTING_MODE_FALLBACK, GROUP_SETTING_MODE_REPLACE) and has_value(group)
    }
    if not by_uuid:
        return None
    return SwitchedOnGroups(
        by_uuid,
        [(uuid, group) for uuid, group in by_uuid.items() if (group.get('url_match_pattern') or '').strip()],
    )


def _first_group(watch, candidates: Optional[SwitchedOnGroups], mode_field, watch_has_own):
    """(group, replaces_watch) of the group that decides for this watch, None when it stays the watch's own or
    the system's. `candidates` is from _switched_on_groups(), `watch_has_own` is only called when it matters."""
    if not candidates:
        return None

    assigned = watch.get('tags') or []
    groups = [candidates.by_uuid[uuid] for uuid in assigned if uuid in candidates.by_uuid]
    if candidates.with_url_pattern:
        watch_url = watch.get('url', '')
        groups += [
            group for uuid, group in candidates.with_url_pattern
            if uuid not in assigned and watch_url and group.matches_url(watch_url)
        ]
    if not groups:
        return None

    for group in groups:
        if group.get(mode_field) == GROUP_SETTING_MODE_REPLACE:
            return group, True

    if not watch_has_own():
        return groups[0], False

    return None


def _group_choice(watch, datastore, field, mode_field, is_set) -> Optional[GroupChoice]:
    """The group that decides this setting for the watch, None when it stays the watch's own or the system's."""
    # Most installations have no group that is switched on, so look for those before any URL matching
    candidates = _switched_on_groups(datastore, mode_field, lambda group: is_set(group.get(field)))
    found = _first_group(watch, candidates, mode_field, lambda: is_set(watch.get(field)))
    if not found:
        return None
    group, replaces_watch = found
    return GroupChoice(group.get(field), group, replaces_watch)


def group_recheck_seconds(group) -> int:
    from changedetectionio.model.Watch import time_between_check_to_seconds
    return time_between_check_to_seconds(group.get('time_between_check'))


def group_time_schedule_limit(group) -> Optional[dict]:
    """The group's time schedule when it is enabled."""
    time_schedule_limit = group.get('time_schedule_limit')
    return time_schedule_limit if time_schedule_limit and time_schedule_limit.get('enabled') else None


def is_recheck_time_set(group) -> bool:
    """An interval, a time schedule, or both. With only a schedule the interval stays the system's."""
    return bool(group_recheck_seconds(group) or group_time_schedule_limit(group))


def groups_with_recheck_time(datastore) -> Optional[SwitchedOnGroups]:
    """The groups whose recheck time is switched on, None when there are none. The scheduler gets this once per
    pass and hands it to recheck_time_group_choice() for every watch, so with nothing switched on the watches
    cost nothing extra."""
    return _switched_on_groups(datastore, RECHECK_TIME_GROUP_MODE_FIELD, is_recheck_time_set)


def recheck_time_group_choice(watch, candidates) -> Optional[GroupChoice]:
    """The group that decides the recheck interval and time schedule for this watch (as .group), None when they
    stay the watch's own or the system's. A watch has its own when 'Use global settings' is not ticked."""
    found = _first_group(watch, candidates, RECHECK_TIME_GROUP_MODE_FIELD,
                         lambda: not watch.get('time_between_check_use_default'))
    if not found:
        return None
    group, replaces_watch = found
    return GroupChoice(group_recheck_seconds(group), group, replaces_watch)


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
