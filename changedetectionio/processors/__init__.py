from abc import abstractmethod
from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.strtobool import strtobool
from copy import deepcopy
from loguru import logger
import hashlib
import os
import re


from .pluggy_interface import plugin_manager, hookimpl

class difference_detection_processor():

    browser_steps = None
    datastore = None
    fetcher = None
    screenshot = None
    watch = None
    xpath_data = None
    preferred_proxy = None

    def __init__(self, *args, datastore, watch_uuid, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore
        self.watch = deepcopy(self.datastore.data['watching'].get(watch_uuid))
        # Generic fetcher that should be extended (requests, playwright etc)
        self.fetcher = Fetcher()

    def call_browser(self, preferred_proxy_id=None):

        from requests.structures import CaseInsensitiveDict

        url = self.watch.link

        # Protect against file:, file:/, file:// access, check the real "link" without any meta "source:" etc prepended.
        if re.search(r'^file:', url.strip(), re.IGNORECASE):
            if not strtobool(os.getenv('ALLOW_FILE_URI', 'false')):
                raise Exception(
                    "file:// type access is denied for security reasons."
                )

        # Requests, playwright, other browser via wss:// etc, fetch_extra_something
        prefer_fetch_backend = self.watch.get('fetch_backend', 'system')

        # Proxy ID "key"
        preferred_proxy_id = preferred_proxy_id if preferred_proxy_id else self.datastore.get_preferred_proxy_for_watch(uuid=self.watch.get('uuid'))

        # Pluggable content self.fetcher
        if not prefer_fetch_backend or prefer_fetch_backend == 'system':
            prefer_fetch_backend = self.datastore.data['settings']['application'].get('fetch_backend')

        # In the case that the preferred fetcher was a browser config with custom connection URL..
        # @todo - on save watch, if its extra_browser_ then it should be obvious it will use playwright (like if its requests now..)
        custom_browser_connection_url = None
        if prefer_fetch_backend.startswith('extra_browser_'):
            (t, key) = prefer_fetch_backend.split('extra_browser_')
            connection = list(
                filter(lambda s: (s['browser_name'] == key), self.datastore.data['settings']['requests'].get('extra_browsers', [])))
            if connection:
                prefer_fetch_backend = 'html_webdriver'
                custom_browser_connection_url = connection[0].get('browser_connection_url')

        # PDF should be html_requests because playwright will serve it up (so far) in a embedded page
        # @todo https://github.com/dgtlmoon/changedetection.io/issues/2019
        # @todo needs test to or a fix
        if self.watch.is_pdf:
           prefer_fetch_backend = "html_requests"

        # Grab the right kind of 'fetcher', (playwright, requests, etc)
        from changedetectionio import content_fetchers
        if hasattr(content_fetchers, prefer_fetch_backend):
            # @todo TEMPORARY HACK - SWITCH BACK TO PLAYWRIGHT FOR BROWSERSTEPS
            if prefer_fetch_backend == 'html_webdriver' and self.watch.has_browser_steps:
                # This is never supported in selenium anyway
                logger.warning("Using playwright fetcher override for possible puppeteer request in browsersteps, because puppetteer:browser steps is incomplete.")
                from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
                fetcher_obj = playwright_fetcher
            else:
                fetcher_obj = getattr(content_fetchers, prefer_fetch_backend)
        else:
            # What it referenced doesnt exist, Just use a default
            fetcher_obj = getattr(content_fetchers, "html_requests")

        proxy_url = None
        if preferred_proxy_id:
            # Custom browser endpoints should NOT have a proxy added
            if not prefer_fetch_backend.startswith('extra_browser_'):
                proxy_url = self.datastore.proxy_list.get(preferred_proxy_id).get('url')
                logger.debug(f"Selected proxy key '{preferred_proxy_id}' as proxy URL '{proxy_url}' for {url}")
            else:
                logger.debug(f"Skipping adding proxy data when custom Browser endpoint is specified. ")

        # Now call the fetcher (playwright/requests/etc) with arguments that only a fetcher would need.
        # When browser_connection_url is None, it method should default to working out whats the best defaults (os env vars etc)
        self.fetcher = fetcher_obj(proxy_override=proxy_url,
                                   custom_browser_connection_url=custom_browser_connection_url
                                   )

        if self.watch.has_browser_steps:
            self.fetcher.browser_steps = self.watch.get('browser_steps', [])
            self.fetcher.browser_steps_screenshot_path = os.path.join(self.datastore.datastore_path, self.watch.get('uuid'))

        # Tweak the base config with the per-watch ones
        from changedetectionio.safe_jinja import render as jinja_render
        request_headers = CaseInsensitiveDict()

        ua = self.datastore.data['settings']['requests'].get('default_ua')
        if ua and ua.get(prefer_fetch_backend):
            request_headers.update({'User-Agent': ua.get(prefer_fetch_backend)})

        request_headers.update(self.watch.get('headers', {}))
        request_headers.update(self.datastore.get_all_base_headers())
        request_headers.update(self.datastore.get_all_headers_in_textfile_for_watch(uuid=self.watch.get('uuid')))

        # https://github.com/psf/requests/issues/4525
        # Requests doesnt yet support brotli encoding, so don't put 'br' here, be totally sure that the user cannot
        # do this by accident.
        if 'Accept-Encoding' in request_headers and "br" in request_headers['Accept-Encoding']:
            request_headers['Accept-Encoding'] = request_headers['Accept-Encoding'].replace(', br', '')

        for header_name in request_headers:
            request_headers.update({header_name: jinja_render(template_str=request_headers.get(header_name))})

        timeout = self.datastore.data['settings']['requests'].get('timeout')

        request_body = self.watch.get('body')
        if request_body:
            request_body = jinja_render(template_str=self.watch.get('body'))
        
        request_method = self.watch.get('method')
        ignore_status_codes = self.watch.get('ignore_status_codes', False)

        # Configurable per-watch or global extra delay before extracting text (for webDriver types)
        system_webdriver_delay = self.datastore.data['settings']['application'].get('webdriver_delay', None)
        if self.watch.get('webdriver_delay'):
            self.fetcher.render_extract_delay = self.watch.get('webdriver_delay')
        elif system_webdriver_delay is not None:
            self.fetcher.render_extract_delay = system_webdriver_delay

        if self.watch.get('webdriver_js_execute_code') is not None and self.watch.get('webdriver_js_execute_code').strip():
            self.fetcher.webdriver_js_execute_code = self.watch.get('webdriver_js_execute_code')

        # Requests for PDF's, images etc should be passwd the is_binary flag
        is_binary = self.watch.is_pdf

        # And here we go! call the right browser with browser-specific settings
        empty_pages_are_a_change = self.datastore.data['settings']['application'].get('empty_pages_are_a_change', False)

        self.fetcher.run(url=url,
                         timeout=timeout,
                         request_headers=request_headers,
                         request_body=request_body,
                         request_method=request_method,
                         ignore_status_codes=ignore_status_codes,
                         current_include_filters=self.watch.get('include_filters'),
                         is_binary=is_binary,
                         empty_pages_are_a_change=empty_pages_are_a_change
                         )

        #@todo .quit here could go on close object, so we can run JS if change-detected
        self.fetcher.quit()

        # After init, call run_changedetection() which will do the actual change-detection

    @abstractmethod
    def run_changedetection(self, watch):
        update_obj = {'last_notification_error': False, 'last_error': False}
        some_data = 'xxxxx'
        update_obj["previous_md5"] = hashlib.md5(some_data.encode('utf-8')).hexdigest()
        changed_detected = False
        return changed_detected, update_obj, ''.encode('utf-8')


def get_all_plugins_info():
    """
    Get information about all registered processor plugins
    :return: A list of dictionaries with plugin info
    """
    plugins_info = []
    
    # Collect from all registered plugins
    for plugin in plugin_manager.get_plugins():
        if hasattr(plugin, "get_processor_name") and hasattr(plugin, "get_processor_description"):
            processor_name = plugin.get_processor_name()
            description = plugin.get_processor_description()
            
            # Get version if available
            version = "N/A"
            if hasattr(plugin, "get_processor_version"):
                plugin_version = plugin.get_processor_version()
                if plugin_version:
                    version = plugin_version
            
            if processor_name and description:
                plugins_info.append({
                    "name": processor_name,
                    "description": description,
                    "version": version
                })
    
    # Fallback if no plugins registered
    if not plugins_info:
        plugins_info = [
            {"name": "text_json_diff", "description": "Webpage Text/HTML, JSON and PDF changes", "version": "1.0.0"},
            {"name": "restock_diff", "description": "Re-stock & Price detection for single product pages", "version": "1.0.0"}
        ]
    
    return plugins_info

def available_processors(datastore=None):
    """
    Get a list of processors by name and description for the UI elements
    Filtered by enabled_plugins setting if datastore is provided
    :return: A list of tuples (processor_name, description)
    """
    plugins_info = get_all_plugins_info()
    processor_list = []

    for plugin in plugins_info:
        processor_list.append((plugin["name"], plugin["description"]))
    
    return processor_list

def get_processor_handler(processor_name, datastore, watch_uuid):
    """
    Get the processor handler for the specified processor name
    :return: The processor handler instance
    """
    # Try each plugin in turn
    for plugin in plugin_manager.get_plugins():
        if hasattr(plugin, "perform_site_check"):
            handler = plugin.perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
            if handler:
                return handler
    
    # If no plugins handled it, use the appropriate built-in processor
    watch = datastore.data['watching'].get(watch_uuid)
    if watch and watch.get('processor') == 'restock_diff':
        from .restock_diff.processor import perform_site_check
        return perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
    else:
        # Default to text_json_diff
        from .text_json_diff.processor import perform_site_check
        return perform_site_check(datastore=datastore, watch_uuid=watch_uuid)

def get_form_class_for_processor(processor_name):
    """
    Get the form class for the specified processor name
    :return: The form class
    """
    # Try each plugin in turn
    for plugin in plugin_manager.get_plugins():
        if hasattr(plugin, "get_form_class"):
            form_class = plugin.get_form_class(processor_name=processor_name)
            if form_class:
                return form_class
    
    # If no plugins provided a form class, use the appropriate built-in form
    if processor_name == 'restock_diff':
        try:
            from .restock_diff.forms import processor_settings_form
            return processor_settings_form
        except ImportError:
            pass
    
    # Default to text_json_diff form
    from changedetectionio import forms
    return forms.processor_text_json_diff_form

def get_watch_model_for_processor(processor_name):
    """
    Get the Watch model class for the specified processor name
    :return: The Watch model class
    """

    # Try each plugin in turn
    for plugin in plugin_manager.get_plugins():
        if hasattr(plugin, "get_watch_model_class"):
            model_class = plugin.get_watch_model_class(processor_name=processor_name)
            if model_class:
                return model_class

    # Default to standard Watch model
    from changedetectionio.model import Watch
    return Watch.model

# Define plugin implementations for the built-in processors
class TextJsonDiffPlugin:
    @hookimpl
    def get_processor_name(self):
        return "text_json_diff"

    @hookimpl
    def get_processor_description(self):
        from .text_json_diff.processor import name
        return name
        
    @hookimpl
    def get_processor_version(self):
        from changedetectionio import __version__
        return __version__

    @hookimpl
    def perform_site_check(self, datastore, watch_uuid):
        watch = datastore.data['watching'].get(watch_uuid)
        if watch and watch.get('processor', 'text_json_diff') == 'text_json_diff':
            from .text_json_diff.processor import perform_site_check
            return perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
        return None

    @hookimpl
    def get_form_class(self, processor_name):
        if processor_name == 'text_json_diff':
            from changedetectionio import forms
            return forms.processor_text_json_diff_form
        return None

    @hookimpl
    def get_watch_model_class(self, processor_name):
        if processor_name == 'text_json_diff':
            from changedetectionio.model import Watch
            return Watch.model
        return None

class RestockDiffPlugin:
    @hookimpl
    def get_processor_name(self):
        return "restock_diff"

    @hookimpl
    def get_processor_description(self):
        from .restock_diff.processor import name
        return name
        
    @hookimpl
    def get_processor_version(self):
        from changedetectionio import __version__
        return __version__

    @hookimpl
    def perform_site_check(self, datastore, watch_uuid):
        watch = datastore.data['watching'].get(watch_uuid)
        if watch and watch.get('processor') == 'restock_diff':
            from .restock_diff.processor import perform_site_check
            return perform_site_check(datastore=datastore, watch_uuid=watch_uuid)
        return None

    @hookimpl
    def get_form_class(self, processor_name):
        if processor_name == 'restock_diff':
            try:
                from .restock_diff.forms import processor_settings_form
                return processor_settings_form
            except ImportError:
                pass
        return None

    @hookimpl
    def get_watch_model_class(self, processor_name):
        if processor_name == 'restock_diff':
            from . import restock_diff
            return restock_diff.Watch
        return None


# Register the built-in processor plugins
plugin_manager.register(TextJsonDiffPlugin())
plugin_manager.register(RestockDiffPlugin())
