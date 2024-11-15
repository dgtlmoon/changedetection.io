#!/usr/bin/env python3

import time

from flask import url_for

from ..html_tools import *
from .util import live_server_setup, wait_for_all_checks


def test_setup(live_server):
    live_server_setup(live_server)

def set_response_with_multiple_index():
    data= """<!DOCTYPE html>
<html>
<body>

<!-- NOTE!! CHROME WILL ADD TBODY HERE IF ITS NOT THERE!! -->
<table style="width:100%">
  <tr>
    <th>Person 1</th>
    <th>Person 2</th>
    <th>Person 3</th>
  </tr>
  <tr>
    <td>Emil</td>
    <td>Tobias</td>
    <td>Linus</td>
  </tr>
  <tr>
    <td>16</td>
    <td>14</td>
    <td>10</td>
  </tr>
</table>
</body>
</html>
"""
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(data)


def set_original_response():
    test_return_data = """<html>
    <header>
    <h2>Header</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A</a></li>
      <li><a href="#">B</a></li>
      <li><a href="#">C</a></li>
    </ul>
    </nav>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
    <div id="changetext">Some text that will change</div>
     </body>
    <footer>
    <p>Footer</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def set_modified_response():
    test_return_data = """<html>
    <header>
    <h2>Header changed</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A changed</a></li>
      <li><a href="#">B</a></li>
      <li><a href="#">C</a></li>
    </ul>
    </nav>
       <body>
     Some initial text<br>
     <p>Which is across multiple lines</p>
     <br>
     So let's see what happens.  <br>
    <div id="changetext">Some text that changes</div>
     </body>
    <footer>
    <p>Footer changed</p>
    </footer>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_element_removal_output():
    from inscriptis import get_text

    # Check text with sub-parts renders correctly
    content = """<html>
    <header>
    <h2>Header</h2>
    </header>
    <nav>
    <ul>
      <li><a href="#">A</a></li>
    </ul>
    </nav>
       <body>
     Some initial text<br>
     <p>across multiple lines</p>
     <div id="changetext">Some text that changes</div>
     <div>Some text should be matched by xPath // selector</div>
     <div>Some text should be matched by xPath selector</div>
     <div>Some text should be matched by xPath1 selector</div>
     </body>
    <footer>
    <p>Footer</p>
    </footer>
     </html>
    """
    html_blob = element_removal(
      [
        "header",
        "footer",
        "nav",
        "#changetext",
        "//*[contains(text(), 'xPath // selector')]",
        "xpath://*[contains(text(), 'xPath selector')]",
        "xpath1://*[contains(text(), 'xPath1 selector')]"
      ],
      html_content=content
    )
    text = get_text(html_blob)
    assert (
        text
        == """Some initial text

across multiple lines
"""
    )


def test_element_removal_full(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_original_response()


    # Add our URL to the import page
    test_url = url_for("test_endpoint", _external=True)
    res = client.post(
        url_for("import_page"), data={"urls": test_url}, follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Goto the edit page, add the filter data
    # Not sure why \r needs to be added - absent of the #changetext this is not necessary
    subtractive_selectors_data = "header\r\nfooter\r\nnav\r\n#changetext"
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "subtractive_selectors": subtractive_selectors_data,
            "url": test_url,
            "tags": "",
            "headers": "",
            "fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Updated watch." in res.data
    wait_for_all_checks(client)

    # Check it saved
    res = client.get(
        url_for("edit_page", uuid="first"),
    )
    assert bytes(subtractive_selectors_data.encode("utf-8")) in res.data

    # Trigger a check
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    wait_for_all_checks(client)

    # so that we set the state to 'unviewed' after all the edits
    client.get(url_for("diff_history_page", uuid="first"))

    #  Make a change to header/footer/nav
    set_modified_response()

    # Trigger a check
    res = client.get(url_for("form_watch_checknow"), follow_redirects=True)
    assert b'1 watches queued for rechecking.' in res.data

    # Give the thread time to pick it up
    wait_for_all_checks(client)

    # There should not be an unviewed change, as changes should be removed
    res = client.get(url_for("index"))
    assert b"unviewed" not in res.data

# Re #2752
def test_element_removal_nth_offset_no_shift(client, live_server, measure_memory_usage):
    #live_server_setup(live_server)

    set_response_with_multiple_index()
    subtractive_selectors_data = ["""
body > table > tr:nth-child(1) > th:nth-child(2)
body > table >  tr:nth-child(2) > td:nth-child(2)
body > table > tr:nth-child(3) > td:nth-child(2)
body > table > tr:nth-child(1) > th:nth-child(3)
body > table >  tr:nth-child(2) > td:nth-child(3)
body > table > tr:nth-child(3) > td:nth-child(3)""",
"""//body/table/tr[1]/th[2]
//body/table/tr[2]/td[2]
//body/table/tr[3]/td[2]
//body/table/tr[1]/th[3]
//body/table/tr[2]/td[3]
//body/table/tr[3]/td[3]"""]

    for selector_list in subtractive_selectors_data:

        res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
        assert b'Deleted' in res.data

        # Add our URL to the import page
        test_url = url_for("test_endpoint", _external=True)
        res = client.post(
            url_for("import_page"), data={"urls": test_url}, follow_redirects=True
        )
        assert b"1 Imported" in res.data
        wait_for_all_checks(client)

        res = client.post(
            url_for("edit_page", uuid="first"),
            data={
                "subtractive_selectors": selector_list,
                "url": test_url,
                "tags": "",
                "fetch_backend": "html_requests",
            },
            follow_redirects=True,
        )
        assert b"Updated watch." in res.data
        wait_for_all_checks(client)

        res = client.get(
            url_for("preview_page", uuid="first"),
            follow_redirects=True
        )

        assert b"Tobias" not in res.data
        assert b"Linus" not in res.data
        assert b"Person 2" not in res.data
        assert b"Person 3" not in res.data
        # First column should exist
        assert b"Emil" in res.data

