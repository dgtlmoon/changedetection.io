available_fetchers = [('json_html_plaintext', 'JSON/HTML/Text'), ('image', 'Graphically by image or web-page')]

class fetch_processor():
    contents = b''
    screenshot = None
    datastore = None

    """
    base class for all fetch processors
    - json_html_plaintext
    - image (future)
    """
