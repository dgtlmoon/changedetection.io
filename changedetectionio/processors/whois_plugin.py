from loguru import logger
import re
import urllib.parse
from .pluggy_interface import hookimpl
from requests.structures import CaseInsensitiveDict
from changedetectionio.content_fetchers.base import Fetcher

# Import the text_json_diff processor
from changedetectionio.processors.text_json_diff.processor import perform_site_check as TextJsonDiffProcessor

# WHOIS Processor implementation that extends TextJsonDiffProcessor
class WhoisProcessor(TextJsonDiffProcessor):
    
    def _extract_domain_from_url(self, url):
        """Extract domain from URL, removing www. prefix if present"""
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        
        # Remove www. prefix if present
        domain = re.sub(r'^www\.', '', domain)
        
        return domain
    
    def call_browser(self, preferred_proxy_id=None):
        """Override call_browser to perform WHOIS lookup instead of using a browser
        
        Note: The python-whois library doesn't directly support proxies. For real proxy support,
        we would need to implement a custom socket connection that routes through the proxy.
        This is a TODO for a future enhancement.
        """
        # Initialize a basic fetcher - this is used by the parent class
        self.fetcher = Fetcher()
        
        # Extract URL from watch
        url = self.watch.link
        
        # Check for file:// access
        if re.search(r'^file:', url.strip(), re.IGNORECASE):
            if not self.datastore.data.get('settings', {}).get('application', {}).get('allow_file_uri', False):
                raise Exception("file:// type access is denied for security reasons.")
        
        # Extract domain from URL
        domain = self._extract_domain_from_url(url)
        
        # Ensure we have a valid domain
        if not domain:
            error_msg = f"Could not extract domain from URL: {url}"
            self.fetcher.content = error_msg
            self.fetcher.status_code = 400
            logger.error(error_msg)
            return
        
        # Get proxy configuration using the common method from parent class
        proxy_config, proxy_url = super()._get_proxy_for_watch(preferred_proxy_id)
        
        try:
            # Use python-whois to get domain information
            import whois
            
            # If we have proxy config, use it for the WHOIS lookup
            # Note: The python-whois library doesn't directly support proxies,
            # but we can implement proxy support if necessary using custom socket code
            if proxy_config:
                # For now, just log that we would use a proxy
                logger.info(f"Using proxy for WHOIS lookup: {proxy_config}")
            
            # Perform the WHOIS lookup
            whois_info = whois.whois(domain)
            
            # Convert whois_info object to text
            if hasattr(whois_info, 'text'):
                # Some whois implementations store raw text in .text attribute
                whois_text = whois_info.text
            else:
                # Otherwise, format it nicely as key-value pairs
                whois_text = f"WHOIS Information for domain: {domain}\n\n"
                for key, value in whois_info.items():
                    if value:
                        whois_text += f"{key}: {value}\n"
            
            # Set the content and status for the fetcher
            self.fetcher.content = whois_text
            self.fetcher.status_code = 200
            
            # Setup headers dictionary for the fetcher
            self.fetcher.headers = CaseInsensitiveDict({
                'content-type': 'text/plain',
                'server': 'whois-processor'
            })
            
            # Add getters for headers
            self.fetcher.get_all_headers = lambda: self.fetcher.headers
            self.fetcher.get_last_status_code = lambda: self.fetcher.status_code
            
            # Implement necessary methods
            self.fetcher.quit = lambda: None
            
        except Exception as e:
            error_msg = f"Error fetching WHOIS data for domain {domain}: {str(e)}"
            self.fetcher.content = error_msg
            self.fetcher.status_code = 500
            self.fetcher.headers = CaseInsensitiveDict({
                'content-type': 'text/plain',
                'server': 'whois-processor'
            })
            self.fetcher.get_all_headers = lambda: self.fetcher.headers
            self.fetcher.get_last_status_code = lambda: self.fetcher.status_code
            self.fetcher.quit = lambda: None
            logger.error(error_msg)
    
    def run_changedetection(self, watch):
        """Use the parent's run_changedetection which will use our overridden call_browser method"""
        try:
            # Let the parent class handle everything now that we've overridden call_browser
            changed_detected, update_obj, filtered_text = super().run_changedetection(watch)
            return changed_detected, update_obj, filtered_text
            
        except Exception as e:
            error_msg = f"Error in WHOIS processor: {str(e)}"
            update_obj = {'last_notification_error': False, 'last_error': error_msg}
            logger.error(error_msg)
            return False, update_obj, error_msg.encode('utf-8')

    @staticmethod
    def perform_site_check(datastore, watch_uuid):
        """Factory method to create a WhoisProcessor instance - for compatibility with legacy code"""
        processor = WhoisProcessor(datastore=datastore, watch_uuid=watch_uuid)
        return processor

@hookimpl
def get_display_link(url, processor_name):
    """Return a custom display link for WHOIS processor
    
    Extract the domain from the URL and return a formatted link that shows
    this is a WHOIS lookup rather than a regular web page.
    """
    if processor_name == 'whois':
        try:
            # Extract domain from URL
            parsed_url = urllib.parse.urlparse(url)
            domain = parsed_url.netloc
            
            # Remove www. prefix if present
            domain = re.sub(r'^www\.', '', domain)
            
            if domain:
                return f"WHOIS - {domain}"
        except Exception as e:
            logger.error(f"Error generating WHOIS display link: {str(e)}")
            return url
    
    return None

@hookimpl
def perform_site_check(datastore, watch_uuid):
    """Create and return a processor instance ready to perform site check"""
    return WhoisProcessor(datastore=datastore, watch_uuid=watch_uuid)

@hookimpl
def get_processor_name():
    """Return the name of this processor"""
    return "whois"

@hookimpl
def get_processor_description():
    """Return the description of this processor"""
    return "WHOIS Domain Information Changes"

@hookimpl
def get_processor_class():
    """Return the processor class"""
    return WhoisProcessor

@hookimpl
def get_processor_form():
    """Return the processor form class"""
    # Import here to avoid circular imports
    from changedetectionio.forms import processor_text_json_diff_form
    return processor_text_json_diff_form

@hookimpl
def get_processor_watch_model():
    """Return the watch model class for this processor"""
    return None  # Use default watch model