import json
from typing import List

from bs4 import BeautifulSoup
from jsonpath_ng.ext import parse
import jq
import re
from inscriptis import get_text
from inscriptis.model.config import ParserConfig

class FilterNotFoundInResponse(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)

class JSONNotFound(ValueError):
    def __init__(self, msg):
        ValueError.__init__(self, msg)


# Given a CSS Rule, and a blob of HTML, return the blob of HTML that matches
def css_filter(css_filter, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    html_block = ""
    r = soup.select(css_filter, separator="")
    if len(html_content) > 0 and len(r) == 0:
        raise FilterNotFoundInResponse(css_filter)
    for item in r:
        html_block += str(item)

    return html_block + "\n"

def subtractive_css_selector(css_selector, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    for item in soup.select(css_selector):
        item.decompose()
    return str(soup)


def element_removal(selectors: List[str], html_content):
    """Joins individual filters into one css filter."""
    selector = ",".join(selectors)
    return subtractive_css_selector(selector, html_content)


# Return str Utf-8 of matched rules
def xpath_filter(xpath_filter, html_content):
    from lxml import etree, html

    tree = html.fromstring(bytes(html_content, encoding='utf-8'))
    html_block = ""

    r = tree.xpath(xpath_filter.strip(), namespaces={'re': 'http://exslt.org/regular-expressions'})
    if len(html_content) > 0 and len(r) == 0:
        raise FilterNotFoundInResponse(xpath_filter)

    #@note: //title/text() wont work where <title>CDATA..

    for element in r:
        if type(element) == etree._ElementStringResult:
            html_block += str(element) + "<br/>"
        elif type(element) == etree._ElementUnicodeResult:
            html_block += str(element) + "<br/>"
        else:
            html_block += etree.tostring(element, pretty_print=True).decode('utf-8') + "<br/>"

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
def _parse_json(json_data, json_filter):
    if 'json:' in json_filter:
        jsonpath_expression = parse(json_filter.replace('json:', ''))
        match = jsonpath_expression.find(json_data)
        return _get_stripped_text_from_json_match(match)
    if 'jq:' in json_filter:
        jq_expression = jq.compile(json_filter.replace('jq:', ''))
        match = jq_expression.input(json_data).all()
        return _get_stripped_text_from_json_match(match)

def _get_stripped_text_from_json_match(match):
    s = []
    # More than one result, we will return it as a JSON list.
    if len(match) > 1:
        for i in match:
            s.append(i.value if hasattr(i, 'value') else i)

    # Single value, use just the value, as it could be later used in a token in notifications.
    if len(match) == 1:
        s = match[0].value if hasattr(match[0], 'value') else match[0]

    # Re #257 - Better handling where it does not exist, in the case the original 's' value was False..
    if not match:
        # Re 265 - Just return an empty string when filter not found
        return ''

    # Ticket #462 - allow the original encoding through, usually it's UTF-8 or similar
    stripped_text_from_html = json.dumps(s, indent=4, ensure_ascii=False)

    return stripped_text_from_html

def extract_json_as_string(content, json_filter):

    stripped_text_from_html = False

    # Try to parse/filter out the JSON, if we get some parser error, then maybe it's embedded <script type=ldjson>
    try:
        stripped_text_from_html = _parse_json(json.loads(content), json_filter)
    except json.JSONDecodeError:

        # Foreach <script json></script> blob.. just return the first that matches json_filter
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
                stripped_text_from_html = _parse_json(json_data, json_filter)
                if stripped_text_from_html:
                    break

    if not stripped_text_from_html:
        # Re 265 - Just return an empty string when filter not found
        return ''

    return stripped_text_from_html

# Mode     - "content" return the content without the matches (default)
#          - "line numbers" return a list of line numbers that match (int list)
#
# wordlist - list of regex's (str) or words (str)
def strip_ignore_text(content, wordlist, mode="content"):
    ignore = []
    ignore_regex = []

    # @todo check this runs case insensitive
    for k in wordlist:

        # Is it a regex?
        if k[0] == '/':
            ignore_regex.append(k.strip(" /"))
        else:
            ignore.append(k)

    i = 0
    output = []
    ignored_line_numbers = []
    for line in content.splitlines():
        i += 1
        # Always ignore blank lines in this mode. (when this function gets called)
        if len(line.strip()):
            regex_matches = False

            # if any of these match, skip
            for regex in ignore_regex:
                try:
                    if re.search(regex, line, re.IGNORECASE):
                        regex_matches = True
                except Exception as e:
                    continue

            if not regex_matches and not any(skip_text.lower() in line.lower() for skip_text in ignore):
                output.append(line.encode('utf8'))
            else:
                ignored_line_numbers.append(i)



    # Used for finding out what to highlight
    if mode == "line numbers":
        return ignored_line_numbers

    return "\n".encode('utf8').join(output)


def html_to_text(html_content: str, render_anchor_tag_content=False) -> str:
    """Converts html string to a string with just the text. If ignoring
    rendering anchor tag content is enable, anchor tag content are also
    included in the text

    :param html_content: string with html content
    :param render_anchor_tag_content: boolean flag indicating whether to extract
    hyperlinks (the anchor tag content) together with text. This refers to the
    'href' inside 'a' tags.
    Anchor tag content is rendered in the following manner:
    '[ text ](anchor tag content)'
    :return: extracted text from the HTML
    """
    #  if anchor tag content flag is set to True define a config for
    #  extracting this content
    if render_anchor_tag_content:

        parser_config = ParserConfig(
            annotation_rules={"a": ["hyperlink"]}, display_links=True
        )

    # otherwise set config to None
    else:
        parser_config = None

    # get text and annotations via inscriptis
    text_content = get_text(html_content, config=parser_config)

    return text_content

def workarounds_for_obfuscations(content):
    """
    Some sites are using sneaky tactics to make prices and other information un-renderable by Inscriptis
    This could go into its own Pip package in the future, for faster updates
    """

    # HomeDepot.com style <span>$<!-- -->90<!-- -->.<!-- -->74</span>
    # https://github.com/weblyzard/inscriptis/issues/45
    if not content:
        return content

    content = re.sub('<!--\s+-->', '', content)

    return content
