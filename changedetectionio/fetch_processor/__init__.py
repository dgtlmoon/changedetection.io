available_fetchers = [('json_html_plaintext', 'JSON/HTML/Text'), ('image', 'Static Image')]

class fetch_processor():
    contents = b''
    screenshot = None
    history_artifact_suffix = 'txt'

    """
    base class for all fetch processors
    - json_html_plaintext
    - image (future)
    """
    def __init__(self, *args, datastore, **kwargs):
        super().__init__(*args, **kwargs)
        self.datastore = datastore

    # If there was a proxy list enabled, figure out what proxy_args/which proxy to use
    # if watch.proxy use that
    # fetcher.proxy_override = watch.proxy or main config proxy
    # Allows override the proxy on a per-request basis
    # ALWAYS use the first one is nothing selected

    def set_proxy_from_list(self, watch):
        proxy_args = None
        if self.datastore.proxy_list is None:
            return None

        # If its a valid one
        if any([watch['proxy'] in p for p in self.datastore.proxy_list]):
            proxy_args = watch['proxy']

        # not valid (including None), try the system one
        else:
            system_proxy = self.datastore.data['settings']['requests']['proxy']
            # Is not None and exists
            if any([system_proxy in p for p in self.datastore.proxy_list]):
                proxy_args = system_proxy

        # Fallback - Did not resolve anything, use the first available
        if proxy_args is None:
            proxy_args = self.datastore.proxy_list[0][0]

        return proxy_args
