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

import os
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

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

    # _save_to_disk() method provided by EntityPersistenceMixin
    # commit() and _get_commit_data() methods inherited from watch_base
    # Tag uses default _get_commit_data() (includes all keys)
