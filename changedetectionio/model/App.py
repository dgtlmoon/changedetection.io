from os import getenv
from copy import deepcopy

from changedetectionio.blueprint.rss import RSS_FORMAT_TYPES, RSS_CONTENT_FORMAT_DEFAULT

from changedetectionio.notification import (
    default_notification_body,
    default_notification_format,
    default_notification_title,
)

from changedetectionio.llm_extractors.base import DEFAULT_EXTRACTION_PROMPT

# Equal to or greater than this number of FilterNotFoundInResponse exceptions will trigger a filter-not-found notification
_FILTER_FAILURE_THRESHOLD_ATTEMPTS_DEFAULT = 6
DEFAULT_SETTINGS_HEADERS_USERAGENT='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.66 Safari/537.36'



class model(dict):
    base_config = {
            'note': "Hello! If you change this file manually, please be sure to restart your changedetection.io instance!",
            'watching': {},
            'settings': {
                'headers': {
                },
                'requests': {
                    'extra_proxies': [], # Configurable extra proxies via the UI
                    'extra_browsers': [],  # Configurable extra proxies via the UI
                    'jitter_seconds': 0,
                    'proxy': None, # Preferred proxy connection
                    'time_between_check': {'weeks': None, 'days': None, 'hours': 3, 'minutes': None, 'seconds': None},
                    'timeout': int(getenv("DEFAULT_SETTINGS_REQUESTS_TIMEOUT", "45")),  # Default 45 seconds
                    'workers': int(getenv("DEFAULT_SETTINGS_REQUESTS_WORKERS", "10")),  # Number of threads, lower is better for slow connections
                    'default_ua': {
                        'html_requests': getenv("DEFAULT_SETTINGS_HEADERS_USERAGENT", DEFAULT_SETTINGS_HEADERS_USERAGENT),
                        'html_webdriver': None,
                    }
                },
                'application': {
                    # Custom notification content
                    'all_paused': False,
                    'all_muted': False,
                    'api_access_token_enabled': True,
                    'base_url' : None,
                    'empty_pages_are_a_change': False,
                    'fetch_backend': getenv("DEFAULT_FETCH_BACKEND", "html_requests"),
                    'filter_failure_notification_threshold_attempts': _FILTER_FAILURE_THRESHOLD_ATTEMPTS_DEFAULT,
                    'global_ignore_text': [], # List of text to ignore when calculating the comparison checksum
                    'global_subtractive_selectors': [],
                    'ignore_whitespace': True,
                    'ignore_status_codes': False, #@todo implement, as ternary.
                    'ssim_threshold': '0.96',  # Default SSIM threshold for screenshot comparison
                    'notification_body': default_notification_body,
                    'notification_format': default_notification_format,
                    'notification_title': default_notification_title,
                    'notification_urls': [], # Apprise URL list
                    'pager_size': 50,
                    'password': False,
                    'render_anchor_tag_content': False,
                    'rss_access_token': None,
                    'rss_content_format': RSS_CONTENT_FORMAT_DEFAULT,
                    'rss_template_type': 'system_default',
                    'rss_template_override': None,
                    'rss_diff_length': 5,
                    'rss_hide_muted_watches': True,
                    'rss_reader_mode': False,
                    'scheduler_timezone_default': None,  # Default IANA timezone name
                    'schema_version' : 0,
                    'shared_diff_access': False,
                    'strip_ignored_lines': False,
                    'tags': {}, #@todo use Tag.model initialisers
                    'webdriver_delay': None , # Extra delay in seconds before extracting text
                    'ui': {
                        'use_page_title_in_list': True,
                        'open_diff_in_new_tab': True,
                        'socket_io_enabled': True,
                        'favicons_enabled': True
                    },
                    # LLM Extraction Settings (disabled by default)
                    'llm_extraction': {
                        'enabled': False,  # Master switch - LLM extraction disabled by default
                        'provider': None,  # 'openai', 'anthropic', or 'ollama'
                        'api_key': None,   # API key (encrypted in storage)
                        'model': None,     # Model name (e.g., 'gpt-4o-mini', 'claude-3-5-haiku')
                        'api_base_url': None,  # Custom API URL (for proxies or self-hosted)
                        'prompt_template': DEFAULT_EXTRACTION_PROMPT,  # Configurable extraction prompt
                        'timeout': 30,     # Request timeout in seconds
                        'fallback_to_css': True,  # Fall back to CSS selectors if LLM fails
                        'max_html_chars': 50000,  # Maximum HTML characters to send to LLM
                    },
                    # LLM Cost Tracking
                    'llm_cost_tracking': {
                        'enabled': True,   # Track costs per API call
                        'total_cost_usd': '0',  # Total cost accumulated (as string decimal)
                        'total_input_tokens': 0,
                        'total_output_tokens': 0,
                        'call_count': 0,   # Number of API calls made
                        'last_reset': None,  # Timestamp of last cost reset
                    },
                }
            }
        }

    def __init__(self, *arg, **kw):
        super(model, self).__init__(*arg, **kw)
        # CRITICAL: deepcopy to avoid sharing mutable objects between instances
        self.update(deepcopy(self.base_config))


def parse_headers_from_text_file(filepath):
    headers = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        for l in f.readlines():
            l = l.strip()
            if not l.startswith('#') and ':' in l:
                (k, v) = l.split(':', 1)  # Split only on the first colon
                headers[k.strip()] = v.strip()

    return headers