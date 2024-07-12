class ProcessorException(Exception):
    def __init__(self, message=None, status_code=None, url=None, screenshot=None, has_filters=False, html_content='', xpath_data=None):
        self.message = message
        self.status_code = status_code
        self.url = url
        self.screenshot = screenshot
        self.has_filters = has_filters
        self.html_content = html_content
        self.xpath_data = xpath_data
        return
