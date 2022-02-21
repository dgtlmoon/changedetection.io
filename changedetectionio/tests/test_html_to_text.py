#!/usr/bin/python3
"""Test suite for the method to extract text from an html string"""
from changedetectionio import fetch_site_status


class MockDataStore:
    """Class to mock the bare minumum data store structure needed to test
    the html to text conversion"""

    def __init__(self, ignore_hyperlinks):
        self.data = {
            "settings": {"application": {"ignore_hyperlinks": ignore_hyperlinks}}
        }


def test_html_to_text_func():
    test_html = """<html>
       <body>
     Some initial text</br>
     <p>Which is across multiple lines</p>
     <a href="/first_link"> More Text </a>
     </br>
     So let's see what happens.  </br>
     <a href="second_link.com"> Even More Text </a>
     </body>
     </html>
    """

    # set the mock data store, with 'ignore hyperlinks' set to True
    mock_data_store = MockDataStore(ignore_hyperlinks=True)

    # extract text
    fetcher = fetch_site_status.perform_site_check(datastore=mock_data_store)
    text_content = fetcher.html_to_text(test_html)

    # check that no links are in the extracted text
    assert (
        text_content == "Some initial text\n\nWhich is across multiple lines\n\nFirst "
        "Link Text So let's see what happens. Second Link Text"
    )

    # set the mock data store, with 'ignore hyperlinks' set to False
    mock_data_store = MockDataStore(ignore_hyperlinks=False)

    # extract text
    fetcher = fetch_site_status.perform_site_check(datastore=mock_data_store)
    text_content = fetcher.html_to_text(test_html)

    # check that links are present in the extracted text
    assert (
        text_content == "Some initial text\n\nWhich is across multiple "
        "lines\n\n[ First Link Text ](/first_link) So let's see what "
        "happens. [ Second Link Text ](second_link.com)"
    )
