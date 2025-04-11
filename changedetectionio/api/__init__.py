import copy
from . import api_schema
from ..model import watch_base

# Build a JSON Schema atleast partially based on our Watch model
watch_base_config = watch_base()
schema = api_schema.build_watch_json_schema(watch_base_config)

schema_create_watch = copy.deepcopy(schema)
schema_create_watch['required'] = ['url']

schema_update_watch = copy.deepcopy(schema)
schema_update_watch['additionalProperties'] = False

# Tag schema is also based on watch_base since Tag inherits from it
schema_tag = copy.deepcopy(schema)
schema_create_tag = copy.deepcopy(schema_tag)
schema_create_tag['required'] = ['title']
schema_update_tag = copy.deepcopy(schema_tag)
schema_update_tag['additionalProperties'] = False

schema_notification_urls = copy.deepcopy(schema)
schema_create_notification_urls = copy.deepcopy(schema_notification_urls)
schema_create_notification_urls['required'] = ['notification_urls']
schema_delete_notification_urls = copy.deepcopy(schema_notification_urls)
schema_delete_notification_urls['required'] = ['notification_urls']

# Import all API resources
from .Watch import Watch, WatchHistory, WatchSingleHistory, CreateWatch
from .Tags import Tags, Tag
from .Import import Import
from .SystemInfo import SystemInfo
from .Notifications import Notifications
