"""
Resolve the full set of NotificationProfile objects that should fire for a given watch.

Merges profile UUIDs from: Watch → Tags → System (union, deduplicated).
Mute cascade is checked separately via resolve_setting() before calling this.
"""

from loguru import logger


def resolve_notification_profiles(watch, datastore) -> list:
    """
    Return list of (profile_dict, NotificationProfileType) tuples to fire for *watch*.

    Profiles are deduplicated by UUID — if the same UUID appears at multiple levels
    it fires once, not multiple times.
    """
    from changedetectionio.notification_profiles.registry import registry

    all_profiles = datastore.data['settings']['application'].get('notification_profile_data', {})

    seen = set()
    result = []

    def _add(uuids):
        for uid in (uuids or []):
            if uid in seen:
                continue
            profile = all_profiles.get(uid)
            if not profile:
                logger.warning(f"Notification profile UUID {uid!r} not found, skipping")
                continue
            seen.add(uid)
            type_handler = registry.get(profile.get('type', 'apprise'))
            result.append((profile, type_handler))

    # 1. Watch-level
    _add(watch.get('notification_profiles', []))

    # 2. Tag/group level
    tags = datastore.get_all_tags_for_watch(uuid=watch.get('uuid'))
    if tags:
        for tag in tags.values():
            _add(tag.get('notification_profiles', []))

    # 3. System level
    _add(datastore.data['settings']['application'].get('notification_profiles', []))

    return result
