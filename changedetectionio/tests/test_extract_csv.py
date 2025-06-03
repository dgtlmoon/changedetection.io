#!/usr/bin/env python3

import time
from flask import url_for
from urllib.request import urlopen
from .util import set_original_response, set_modified_response, live_server_setup, wait_for_all_checks

sleep_time_for_fetch_thread = 3



def test_check_extract_text_from_diff(client, live_server, measure_memory_usage):
    import time
    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write("Now it's {} seconds since epoch, time flies!".format(str(time.time())))

   #  live_server_setup(live_server) # Setup on conftest per function

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": url_for('test_endpoint', _external=True)},
        follow_redirects=True
    )

    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Load in 5 different numbers/changes
    last_date=""
    for n in range(5):
        time.sleep(1)
        # Give the thread time to pick it up
        print("Bumping snapshot and checking.. ", n)
        last_date = str(time.time())
        with open("test-datastore/endpoint-content.txt", "w") as f:
            f.write("Now it's {} seconds since epoch, time flies!".format(last_date))

        client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

    res = client.post(
        url_for("ui.ui_views.diff_history_page", uuid="first"),
        data={"extract_regex": "Now it's ([0-9\.]+)",
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

    # Header line + 1 origin/first + 5 changes
    assert(len(output) == 7)

    # We expect to find the last bumped date in the changes in the last field of the spreadsheet
    assert(output[6][2] == last_date)
    # And nothing else, only that group () of the decimal and .
    assert "time flies" not in output[6][2]
