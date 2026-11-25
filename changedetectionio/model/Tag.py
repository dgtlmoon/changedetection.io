"""
Tag/Group domain model for organizing and overriding watch settings.

ARCHITECTURE NOTE: Configuration Override Hierarchy
===================================================

Tags can override Watch settings when overrides_watch=True.
Current implementation requires manual checking in processors:

    for tag_uuid in watch.get('tags'):
        tag = datastore['settings']['application']['tags'][tag_uuid]
        if tag.get('overrides_watch'):
            restock_settings = tag.get('restock_settings', {})
            break

With Pydantic, this would be automatic via chain resolution:
    Watch → Tag (first with overrides_watch) → Global

See: Watch.py model docstring for full Pydantic architecture explanation
See: processors/restock_diff/processor.py:184-192 for current manual implementation
"""

from changedetectionio.model import watch_base
from changedetectionio.model.persistence import EntityPersistenceMixin

class model(EntityPersistenceMixin, watch_base):
    """
    Tag domain model - groups watches and can override their settings.

    Tags inherit from watch_base to reuse all the same fields as Watch.
    When overrides_watch=True, tag settings take precedence over watch settings
    for all watches in this tag/group.

    Fields:
        overrides_watch (bool): If True, this tag's settings override watch settings
        title (str): Display name for this tag/group
        uuid (str): Unique identifier
        ... (all fields from watch_base can be set as tag-level overrides)

    Resolution order when overrides_watch=True:
        Watch.field → Tag.field (if overrides_watch) → Global.field
    """

    def __init__(self, *arg, **kw):
        # Parent class (watch_base) handles __datastore and __datastore_path
        super(model, self).__init__(*arg, **kw)

        self['overrides_watch'] = kw.get('default', {}).get('overrides_watch')
        # Ternary on a tag, unlike the plain bool on a watch: None ("leave it to each watch")
        # is the default, so a group never touches its watches' AI until explicitly set.
        # See llm/evaluator.py:tag_llm_decision().
        self['llm_backend_profile'] = kw.get('default', {}).get('llm_backend_profile', None)
        self['url_match_pattern'] = kw.get('default', {}).get('url_match_pattern', '')
        # 'off' so a new group's notification settings do nothing until switched on. Groups from before 'off'
        # existed got their mode from update_36, see notification.group_notification_mode_for_older_data()
        self['notification_group_mode'] = kw.get('default', {}).get('notification_group_mode', 'off')
        # 'off' so a group's fetch method / proxy / recheck time does nothing until it is switched on, see model/group_settings.py
        self['fetch_backend_group_mode'] = kw.get('default', {}).get('fetch_backend_group_mode', 'off')
        self['proxy_group_mode'] = kw.get('default', {}).get('proxy_group_mode', 'off')
        self['time_between_check_group_mode'] = kw.get('default', {}).get('time_between_check_group_mode', 'off')

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

    def url_matcher(self):
        """A function that says whether a (lower-cased) URL matches this tag's pattern, None if no pattern is
        configured. For asking about many URLs: the pattern is prepared once.

        Wildcard patterns (*,?,[ ) use fnmatch; anything else is a case-insensitive substring match.
        """
        import fnmatch
        import re
        pattern = self.get('url_match_pattern', '').strip().lower()
        if not pattern:
            return None
        if any(c in pattern for c in ('*', '?', '[')):
            return re.compile(fnmatch.translate(pattern)).match
        return lambda url: pattern in url

    def matches_url(self, url: str) -> bool:
        """Return True if this tag should be auto-applied to the given watch URL, see url_matcher().
        Returns False if no pattern is configured."""
        if not url:
            return False
        matcher = self.url_matcher()
        return bool(matcher and matcher(url.lower()))

    # _save_to_disk() method provided by EntityPersistenceMixin
    # commit() and _get_commit_data() methods inherited from watch_base
    # Tag uses default _get_commit_data() (includes all keys)
