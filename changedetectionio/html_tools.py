import json
from bs4 import BeautifulSoup
from jsonpath_ng.ext import parse


class JSONNotFound(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)

# Given a CSS Rule, and a blob of HTML, return the blob of HTML that matches
def css_filter(css_filter, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    html_block = ""
    for item in soup.select(css_filter, separator=""):
        html_block += str(item)

    return html_block + "\n"


# Return str Utf-8 of matched rules
def xpath_filter(xpath_filter, html_content):
    from lxml import html
    from lxml import etree

    tree = html.fromstring(html_content)
    html_block = ""

    for item in tree.xpath(xpath_filter.strip()):
        html_block+= etree.tostring(item, pretty_print=True).decode('utf-8')+"<br/>"

    return html_block


# Extract/find element
def extract_element(find='title', html_content=''):

    #Re #106, be sure to handle when its not found
    element_text = None

    soup = BeautifulSoup(html_content, 'html.parser')
    result = soup.find(find)
    if result and result.string:
        element_text = result.string.strip()

    return element_text

#
def _parse_json(json_data, jsonpath_filter):
    s=[]
    jsonpath_expression = parse(jsonpath_filter.replace('json:', ''))
    match = jsonpath_expression.find(json_data)

    # More than one result, we will return it as a JSON list.
    if len(match) > 1:
        for i in match:
            s.append(i.value)

    # Single value, use just the value, as it could be later used in a token in notifications.
    if len(match) == 1:
        s = match[0].value

    # Re #257 - Better handling where it does not exist, in the case the original 's' value was False..
    if not match:
        # Re 265 - Just return an empty string when filter not found
        return ''

    stripped_text_from_html = json.dumps(s, indent=4)

    return stripped_text_from_html

def extract_json_as_string(content, jsonpath_filter):

    stripped_text_from_html = False

    # Try to parse/filter out the JSON, if we get some parser error, then maybe it's embedded <script type=ldjson>
    try:
        stripped_text_from_html = _parse_json(json.loads(content), jsonpath_filter)
    except json.JSONDecodeError:

        # Foreach <script json></script> blob.. just return the first that matches jsonpath_filter
        s = []
        soup = BeautifulSoup(content, 'html.parser')
        bs_result = soup.findAll('script')

        if not bs_result:
            raise JSONNotFound("No parsable JSON found in this document")

        for result in bs_result:
            # Skip empty tags, and things that dont even look like JSON
            if not result.string or not '{' in result.string:
                continue
                
            try:
                json_data = json.loads(result.string)
            except json.JSONDecodeError:
                # Just skip it
                continue
            else:
                stripped_text_from_html = _parse_json(json_data, jsonpath_filter)
                if stripped_text_from_html:
                    break

    if not stripped_text_from_html:
        # Re 265 - Just return an empty string when filter not found
        return ''

    return stripped_text_from_html
