from abc import abstractmethod
from changedetectionio.content_fetchers.base import Fetcher
from changedetectionio.strtobool import strtobool
from copy import deepcopy
from loguru import logger

import hashlib
import importlib
import inspect
import os
import pkgutil
import re

# Import the plugin manager
from .pluggy_interface import plugin_manager


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
        
    def _get_proxy_for_watch(self, preferred_proxy_id=None):
        """Get proxy configuration based on watch settings and preferred proxy ID
        
        Args:
            preferred_proxy_id: Optional explicit proxy ID to use
            
        Returns:
            dict: Proxy configuration or None if no proxy should be used
            str: Proxy URL or None if no proxy should be used
        """
        # Default to no proxy config
        proxy_config = None
        proxy_url = None
        
        # Check if datastore is available and has get_preferred_proxy_for_watch method
        if hasattr(self, 'datastore') and self.datastore:
            try:
                # Get preferred proxy ID if not provided
                if not preferred_proxy_id and hasattr(self.datastore, 'get_preferred_proxy_for_watch'):
                    # Get the watch UUID if available
                    watch_uuid = None
                    if hasattr(self.watch, 'get'):
                        watch_uuid = self.watch.get('uuid')
                    elif hasattr(self.watch, 'uuid'):
                        watch_uuid = self.watch.uuid
                    
                    if watch_uuid:
                        preferred_proxy_id = self.datastore.get_preferred_proxy_for_watch(uuid=watch_uuid)
                
                # Check if we have a proxy list and a valid proxy ID
                if preferred_proxy_id and hasattr(self.datastore, 'proxy_list') and self.datastore.proxy_list:
                    proxy_info = self.datastore.proxy_list.get(preferred_proxy_id)
                    
                    if proxy_info and 'url' in proxy_info:
                        proxy_url = proxy_info.get('url')
                        logger.debug(f"Selected proxy key '{preferred_proxy_id}' as proxy URL '{proxy_url}'")
                        
                        # Parse the proxy URL to build a proxy dict for requests
                        import urllib.parse
                        parsed_proxy = urllib.parse.urlparse(proxy_url)
                        proxy_type = parsed_proxy.scheme
                        
                        # Extract credentials if present
                        username = None
                        password = None
                        if parsed_proxy.username:
                            username = parsed_proxy.username
                            if parsed_proxy.password:
                                password = parsed_proxy.password
                        
                        # Build the proxy URL without credentials for the proxy dict
                        netloc = parsed_proxy.netloc
                        if '@' in netloc:
                            netloc = netloc.split('@')[1]
                        
                        proxy_addr = f"{proxy_type}://{netloc}"
                        
                        # Create the proxy configuration
                        proxy_config = {
                            'http': proxy_addr,
                            'https': proxy_addr
                        }
                        
                        # Add credentials if present
                        if username:
                            proxy_config['username'] = username
                            if password:
                                proxy_config['password'] = password
            except Exception as e:
                # Log the error but continue without a proxy
                logger.error(f"Error setting up proxy: {str(e)}")
                proxy_config = None
                proxy_url = None
                
        return proxy_config, proxy_url

    def call_browser(self, preferred_proxy_id=None):
        """Fetch content using the appropriate browser/fetcher
        
        This method will:
        1. Determine the appropriate fetcher to use based on watch settings
        2. Set up proxy configuration if needed
        3. Initialize the fetcher with the correct parameters
        4. Configure any browser steps if needed
        
        Args:
            preferred_proxy_id: Optional explicit proxy ID to use
        """
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

        # Get proxy configuration
        proxy_config, proxy_url = self._get_proxy_for_watch(preferred_proxy_id)

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

        # Custom browser endpoints should NOT have a proxy added
        if proxy_url and prefer_fetch_backend.startswith('extra_browser_'):
            logger.debug(f"Skipping adding proxy data when custom Browser endpoint is specified.")
            proxy_url = None

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


def find_sub_packages(package_name):
    """
    Find all sub-packages within the given package.

    :param package_name: The name of the base package to scan for sub-packages.
    :return: A list of sub-package names.
    """
    package = importlib.import_module(package_name)
    return [name for _, name, is_pkg in pkgutil.iter_modules(package.__path__) if is_pkg]


def find_processors():
    """
    Find all subclasses of DifferenceDetectionProcessor in the specified package
    and also include processors from the plugin system.

    :return: A list of (module, class) tuples.
    """
    package_name = "changedetectionio.processors"  # Name of the current package/module

    processors = []
    sub_packages = find_sub_packages(package_name)

    # Find traditional processors
    for sub_package in sub_packages:
        module_name = f"{package_name}.{sub_package}.processor"
        try:
            module = importlib.import_module(module_name)

            # Iterate through all classes in the module
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, difference_detection_processor) and obj is not difference_detection_processor:
                    processors.append((module, sub_package))
        except (ModuleNotFoundError, ImportError) as e:
            logger.warning(f"Failed to import module {module_name}: {e} (find_processors())")

    # Also include processors from the plugin system
    try:
        from .processor_registry import get_plugin_processor_modules
        plugin_modules = get_plugin_processor_modules()
        if plugin_modules:
            processors.extend(plugin_modules)
    except (ImportError, ModuleNotFoundError) as e:
        logger.warning(f"Failed to import plugin modules: {e} (find_processors())")

    return processors


def get_parent_module(module):
    module_name = module.__name__
    if '.' not in module_name:
        return None  # Top-level module has no parent
    parent_module_name = module_name.rsplit('.', 1)[0]
    try:
        return importlib.import_module(parent_module_name)
    except Exception as e:
        pass

    return False


def get_custom_watch_obj_for_processor(processor_name):
    """
    Get the custom watch object for a processor
    :param processor_name: Name of the processor
    :return: Watch class or None
    """
    # First, try to get the watch model from the pluggy system
    try:
        from .processor_registry import get_processor_watch_model
        watch_model = get_processor_watch_model(processor_name)
        if watch_model:
            return watch_model
    except Exception as e:
        logger.warning(f"Error getting processor watch model from pluggy: {e}")

    # Fall back to the traditional approach
    from changedetectionio.model import Watch
    watch_class = Watch.model
    processor_classes = find_processors()
    custom_watch_obj = next((tpl for tpl in processor_classes if tpl[1] == processor_name), None)
    if custom_watch_obj:
        # Parent of .processor.py COULD have its own Watch implementation
        parent_module = get_parent_module(custom_watch_obj[0])
        if hasattr(parent_module, 'Watch'):
            watch_class = parent_module.Watch

    return watch_class


def available_processors():
    """
    Get a list of processors by name and description for the UI elements
    :return: A list of tuples (processor_name, description)
    """
    # Get processors from the pluggy system
    pluggy_processors = []
    try:
        from .processor_registry import get_all_processors
        pluggy_processors = get_all_processors()
    except Exception as e:
        logger.error(f"Error getting processors from pluggy: {str(e)}")
    
    # Get processors from the traditional file-based system
    traditional_processors = []
    try:
        # Let's not use find_processors() directly since it now also includes pluggy processors
        package_name = "changedetectionio.processors"
        sub_packages = find_sub_packages(package_name)
        
        for sub_package in sub_packages:
            module_name = f"{package_name}.{sub_package}.processor"
            try:
                module = importlib.import_module(module_name)
                # Get the name and description from the module if available
                name = getattr(module, 'name', f"Traditional processor: {sub_package}")
                description = getattr(module, 'description', sub_package)
                traditional_processors.append((sub_package, name))
            except (ModuleNotFoundError, ImportError, AttributeError) as e:
                logger.warning(f"Failed to import module {module_name}: {e} (available_processors())")
    except Exception as e:
        logger.error(f"Error getting traditional processors: {str(e)}")
    
    # Combine the lists, ensuring no duplicates
    # Pluggy processors take precedence
    all_processors = []
    
    # Add all pluggy processors
    all_processors.extend(pluggy_processors)
    
    # Add traditional processors that aren't already registered via pluggy
    pluggy_processor_names = [name for name, _ in pluggy_processors]
    for processor_class, name in traditional_processors:
        if processor_class not in pluggy_processor_names:
            all_processors.append((processor_class, name))
    
    return all_processors