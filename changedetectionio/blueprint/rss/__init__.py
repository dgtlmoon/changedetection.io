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

RSS_TEMPLATE_TYPE_OPTIONS = {'system_default': 'System default', 'notification_body': 'Notification body'}

# @note: We use <pre> because nearly all RSS readers render only HTML (Thunderbird for example cant do just plaintext)
RSS_TEMPLATE_PLAINTEXT_DEFAULT = "<pre>{{watch_label}} had a change.\n\n{{diff}}\n</pre>"

# @todo add some [edit]/[history]/[goto] etc links
# @todo need {{watch_edit_link}} + delete + history link token
RSS_TEMPLATE_HTML_DEFAULT = "<html><body>\n<h4><a href=\"{{watch_url}}\">{{watch_label}}</a></h4>\n<p>{{diff}}</p>\n</body></html>\n"
