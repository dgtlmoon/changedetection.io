from bs4 import BeautifulSoup


# Given a CSS Rule, and a blob of HTML, return the blob of HTML that matches
def css_filter(css_filter, html_content):
    soup = BeautifulSoup(html_content, "html.parser")
    html_block = ""
    for item in soup.select(css_filter, separator=""):
        html_block += str(item)

    return html_block + "\n"

def extract_title(html_content):
    html_title = False

    soup = BeautifulSoup(html_content, 'html.parser')
    title = soup.find('title')
    if title:
        html_title = title.string.strip()

    return html_title