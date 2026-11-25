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
    # uuid -> GroupChoice, made once so that asking for a watch creates nothing
    choices: dict
    # (uuid, GroupChoice, Tag.url_matcher()) of the ones that also apply by URL pattern, only those are matched
    # against a watch's URL
    with_url_pattern: list


def _switched_on_groups(datastore, mode_field, has_value, value_of) -> Optional[SwitchedOnGroups]:
    """The groups that are switched on for this setting and have something to give, None when there are none."""
    all_groups = datastore.data['settings']['application'].get('tags') or {}
    choices = {}
    for uuid, group in all_groups.items():
        mode = group.get(mode_field)
        if mode in (GROUP_SETTING_MODE_FALLBACK, GROUP_SETTING_MODE_REPLACE) and has_value(group):
            choices[uuid] = GroupChoice(value_of(group), group, mode == GROUP_SETTING_MODE_REPLACE)
    if not choices:
        return None
    with_url_pattern = []
    for uuid, choice in choices.items():
        matcher = choice.group.url_matcher()
        if matcher:
            with_url_pattern.append((uuid, choice, matcher))
    return SwitchedOnGroups(choices, with_url_pattern)


def _first_choice(watch, candidates: SwitchedOnGroups) -> Optional[GroupChoice]:
    """The first group that replaces the watch's own, else the first one that is a fallback (the caller then looks
    at whether the watch has its own), else None. Groups in the order of the watch's own list, then the ones
    applied by URL pattern."""
    choices = candidates.choices
    assigned = watch.get('tags') or ()
    fallback = None
    for uuid in assigned:
        choice = choices.get(uuid)
        if choice:
            if choice.replaces_watch:
                return choice
            if fallback is None:
                fallback = choice

    if candidates.with_url_pattern:
        watch_url = (watch.get('url') or '').lower()
        if watch_url:
            for uuid, choice, matches in candidates.with_url_pattern:
                if uuid not in assigned and matches(watch_url):
                    if choice.replaces_watch:
                        return choice
                    if fallback is None:
                        fallback = choice

    return fallback


def _group_choice(watch, datastore, field, mode_field, is_set) -> Optional[GroupChoice]:
    """The group that decides this setting for the watch, None when it stays the watch's own or the system's."""
    # Most installations have no group that is switched on, so look for those before any URL matching
    candidates = _switched_on_groups(datastore, mode_field,
                                     has_value=lambda group: is_set(group.get(field)),
                                     value_of=lambda group: group.get(field))
    if not candidates:
        return None
    choice = _first_choice(watch, candidates)
    if choice and not choice.replaces_watch and is_set(watch.get(field)):
        return None
    return choice


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
    pass and hands it to recheck_time_group_choice() for every watch: everything about the groups is worked out
    here, so per watch it is a lookup of the watch's own group list."""
    return _switched_on_groups(datastore, RECHECK_TIME_GROUP_MODE_FIELD,
                               has_value=is_recheck_time_set, value_of=group_recheck_seconds)


def recheck_time_group_choice(watch, candidates: Optional[SwitchedOnGroups]) -> Optional[GroupChoice]:
    """The group that decides the recheck interval (.value, seconds) and time schedule (of .group) for this watch,
    None when they stay the watch's own or the system's. A watch has its own when 'Use global settings' is not
    ticked."""
    if not candidates:
        return None
    choice = _first_choice(watch, candidates)
    if choice and not choice.replaces_watch and not watch.get('time_between_check_use_default'):
        return None
    return choice


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
