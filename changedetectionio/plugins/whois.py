"""
Whois information lookup
- Fetches using whois
- Extends the 'text_json_diff' so that text filters can still be used with whois information

@todo publish to pypi and github as a separate plugin
"""

from ..plugins import hookimpl
import changedetectionio.processors.text_json_diff as text_json_diff
from changedetectionio import content_fetcher

# would be changedetectionio.plugins in other apps

class text_json_filtering_whois(text_json_diff.perform_site_check):

    def __init__(self, *args, datastore, watch_uuid, **kwargs):
        super().__init__(*args, datastore=datastore, watch_uuid=watch_uuid, **kwargs)

    def call_browser(self):
        import whois
        # the whois data
        self.fetcher = content_fetcher.Fetcher()
        self.fetcher.is_plaintext = True

        from urllib.parse import urlparse
        parsed = urlparse(self.watch.link)
        w = whois.whois(parsed.hostname)
        self.fetcher.content= w.text

@hookimpl
def extra_processor():
    """
    Advertise a new processor
    :return:
    """
    from changedetectionio.processors import default_processor_config
    processor_config = dict(default_processor_config)
    # Which UI elements are not used
    processor_config['needs_request_fetch_method'] = False
    processor_config['needs_browsersteps'] = False
    processor_config['needs_visualselector'] = False
    return ('plugin_processor_whois', "Whois domain information fetch", processor_config)

# @todo When a watch chooses this extra_process processor, the watch should ONLY use this one.
#       (one watch can only have one extra_processor)
@hookimpl
def processor_call(processor_name, datastore, watch_uuid):
    if processor_name == 'plugin_processor_whois': # could be removed, see above note
        x = text_json_filtering_whois(datastore=datastore, watch_uuid=watch_uuid)
        return x
    return None

