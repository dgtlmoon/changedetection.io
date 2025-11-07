from copy import deepcopy
from loguru import logger

from changedetectionio.model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH
from changedetectionio.notification import valid_notification_formats
RSS_CONTENT_FORMAT_DEFAULT = 'text'

# Some stuff not related
RSS_FORMAT_TYPES = deepcopy(valid_notification_formats)
if RSS_FORMAT_TYPES.get('markdown'):
    del RSS_FORMAT_TYPES['markdown']

if RSS_FORMAT_TYPES.get(USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH):
    del RSS_FORMAT_TYPES[USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH]

if not RSS_FORMAT_TYPES.get(RSS_CONTENT_FORMAT_DEFAULT):
    logger.critical(f"RSS_CONTENT_FORMAT_DEFAULT not in the acceptable list {RSS_CONTENT_FORMAT_DEFAULT}")
