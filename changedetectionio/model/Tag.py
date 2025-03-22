
import os
import json
import uuid as uuid_builder
import time
from copy import deepcopy
from loguru import logger

from changedetectionio.model import watch_base, schema


class model(watch_base):
    """Tag model that writes to tags/{uuid}/tag.json instead of the main watch directory"""
    __datastore_path = None

    def __init__(self, *arg, **kw):
        super(model, self).__init__(*arg, **kw)
        self.__datastore_path = kw.get("datastore_path")

        self['overrides_watch'] = kw.get('default', {}).get('overrides_watch')

        if kw.get('default'):
            self.update(kw['default'])
            del kw['default']

    @property
    def watch_data_dir(self):
        # Override to use tags directory instead of the normal watch data directory
        datastore_path = getattr(self, '_model__datastore_path', None)
        if datastore_path:
            tags_path = os.path.join(datastore_path, 'tags')
            # Make sure the tags directory exists
            if not os.path.exists(tags_path):
                os.makedirs(tags_path)
            return os.path.join(tags_path, self['uuid'])
        return None
        
    def save_data(self):
        """Override to save tag to tags/{uuid}/tag.json"""
        logger.debug(f"Saving tag {self['uuid']}")

        if not self.get('uuid'):
            # Might have been called when creating the tag
            return

        tags_path = os.path.join(self.__datastore_path, 'tags')
        if not os.path.isdir(tags_path):
            os.mkdir(os.path.join(tags_path))

        path = os.path.join(tags_path, self.get('uuid')+".json")
        try:
            with open(path + ".tmp", 'w') as json_file:
                json.dump(self.get_data(), json_file, indent=4)
            os.replace(path + ".tmp", path)
        except Exception as e:
            logger.error(f"Error writing JSON for tag {self.get('uuid')}!! (JSON file save was skipped) : {str(e)}")

