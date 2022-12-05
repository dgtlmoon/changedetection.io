#!/usr/bin/python3

import time
from flask import url_for
from urllib.request import urlopen
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks

sleep_time_for_fetch_thread = 3



def test_check_extract_text_from_diff(client, live_server):
    import time
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("Now it's {} seconds since epoch, time flies!".format(str(time.time())))

    live_server_setup(live_server)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    time.sleep(2)

    # Load in 5 different numbers/changes
    for n in range(5):
        # Give the thread time to pick it up
        wait_for_all_checks(client)

        with open("test-datastore/endpoint-content.txt", "w") as f:
            f.write("Now it's {} seconds since epoch, time flies!".format(str(time.time())))

        client.get(url_for("form_watch_checknow"), follow_redirects=True)


    res = client.post(
        url_for("diff_history_page", uuid="first"),
        data={"extract_regex": "Now it's ([0-9]+)",
              "extract_submit_button": "Extract as CSV"},
        follow_redirects=False
    )

    assert b'Nothing matches that RegEx' not in res.data
    assert res.content_type == 'text/csv'

    # Read the csv reply as stringio
    from io import StringIO
    import csv

    f = StringIO(res.data.decode('utf-8'))
    reader = csv.reader(f, delimiter=',')
    output=[]

    for row in reader:
        output.append(row)

    assert output[0][0] == 'Epoch seconds'
    # Header line + 5 outputs
    assert(len(output) == 6)
