"""
Unified Watch → Tag → Global settings cascade resolver.

All settings resolution follows the same priority order:
  1. Watch-level setting (if set and not a sentinel "use parent" value)
  2. First tag with overrides_watch=True that has the field set
  3. Global application settings
  4. Caller-supplied default

This replaces the previously scattered manual resolution loops found in
notification_service.py, processors/base.py, and the restock processor.
"""


def resolve_setting(watch, datastore, field_name, *,
                    sentinel_values=None,
                    default=None,
                    require_tag_override=True):
    """
    Resolve a single setting value by walking the Watch → Tag → Global chain.

    Args:
        watch:               Watch dict / model object.
        datastore:           App datastore (must have get_all_tags_for_watch() and
                             data['settings']['application']).
        field_name:          The setting key to look up at each level.
        sentinel_values:     Set of values that mean "not configured here, keep looking".
                             For example {'system'} for fetch_backend.
        default:             Value returned when nothing is found in the chain.
        require_tag_override: If True (default), only tags where overrides_watch=True
                             contribute to the cascade.  Set to False when every tag
                             that carries the field should be considered (e.g. for
                             fields that make sense to merge/override at any tag level).

    Returns:
        The first non-sentinel, non-empty value found, or *default*.
    """
    _sentinels = set(sentinel_values) if sentinel_values else set()

    def _is_unset(v):
        return v is None or v == '' or v in _sentinels

    # 1. Watch level
    v = watch.get(field_name)
    if not _is_unset(v):
        return v

    # 2. Tag level
    tags = datastore.get_all_tags_for_watch(uuid=watch.get('uuid'))
    if tags:
        for tag in tags.values():
            if require_tag_override and not tag.get('overrides_watch'):
                continue
            v = tag.get(field_name)
            if not _is_unset(v):
                return v

    # 3. Global application settings
    v = datastore.data['settings']['application'].get(field_name)
    if not _is_unset(v):
        return v

    return default
