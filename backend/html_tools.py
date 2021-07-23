from bs4 import BeautifulSoup


# Given a CSS Rule, and a blob of HTML, return the blob of HTML that matches
def css_filter(css_filter, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    html_block = ""
    for item in soup.select(css_filter, separator=""):
        html_block += str(item)

    return html_block + "\n"


# Extract/find element
def extract_element(find='title', html_content=''):

    #Re #106, be sure to handle when its not found
    element_text = None

    soup = BeautifulSoup(html_content, 'html.parser')
    result = soup.find(find)
    if result and result.string:
        element_text = result.string.strip()

    return element_text

def extract_json_as_string(content, jsonpath_filter):
    # POC hack, @todo rename vars, see how it fits in with the javascript version
    import json
    from jsonpath_ng import jsonpath, parse

    json_data = json.loads(content)
    jsonpath_expression = parse(jsonpath_filter.replace('json:', ''))
    match = jsonpath_expression.find(json_data)
    s = []

    # More than one result, we will return it as a JSON list.
    if len(match) > 1:
        for i in match:
            s.append(i.value)

    # Single value, use just the value, as it could be later used in a token in notifications.
    if len(match) == 1:
        s = match[0].value

    stripped_text_from_html = json.dumps(s, indent=4)

    return stripped_text_from_html
