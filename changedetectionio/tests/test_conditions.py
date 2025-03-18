#!/usr/bin/env python3
import json
import urllib

from flask import url_for
from .util import live_server_setup, wait_for_all_checks

def set_original_response(number="50"):
    test_return_data = f"""<html>
       <body>
     <h1>Test Page for Conditions</h1>
     <p>This page contains a number that will be tested with conditions.</p>
     <div class="number-container">Current value: {number}</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def set_number_in_range_response(number="75"):
    test_return_data = f"""<html>
       <body>
     <h1>Test Page for Conditions</h1>
     <p>This page contains a number that will be tested with conditions.</p>
     <div class="number-container">Current value: {number}</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)

def set_number_out_of_range_response(number="150"):
    test_return_data = f"""<html>
       <body>
     <h1>Test Page for Conditions</h1>
     <p>This page contains a number that will be tested with conditions.</p>
     <div class="number-container">Current value: {number}</div>
     </body>
     </html>
    """

    with open("test-datastore/endpoint-content.txt", "w") as f:
        f.write(test_return_data)


def test_conditions_with_text_and_number(client, live_server):
    """Test that both text and number conditions work together with AND logic."""
    
    set_original_response("50")
    live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    # Configure the watch with two conditions connected with AND:
    # 1. The page filtered text must contain "5" (first digit of value)
    # 2. The extracted number should be >= 20 and <= 100
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "include_filters": ".number-container",
            "title": "Number AND Text Condition Test",
            "conditions_match_logic": "ALL",  # ALL = AND logic
            "conditions-0-operator": "in",
            "conditions-0-field": "page_filtered_text",
            "conditions-0-value": "5",

            "conditions-1-operator": ">=",
            "conditions-1-field": "extracted_number",
            "conditions-1-value": "20",

            "conditions-2-operator": "<=",
            "conditions-2-field": "extracted_number",
            "conditions-2-value": "100",

            # So that 'operations' from pluggy discovery are tested
            "conditions-3-operator": "length_min",
            "conditions-3-field": "page_filtered_text",
            "conditions-3-value": "1",

            # So that 'operations' from pluggy discovery are tested
            "conditions-4-operator": "length_max",
            "conditions-4-field": "page_filtered_text",
            "conditions-4-value": "100",

            # So that 'operations' from pluggy discovery are tested
            "conditions-5-operator": "contains_regex",
            "conditions-5-field": "page_filtered_text",
            "conditions-5-value": "\d",
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    wait_for_all_checks(client)
    client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    wait_for_all_checks(client)

    # Case 1
    set_number_in_range_response("70.5")
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # 75 is > 20 and < 100 and contains "5"
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data


    # Case 2: Change with one condition violated
    # Number out of range (150) but contains '5'
    client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    set_number_out_of_range_response("150.5")


    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should NOT be marked as having changes since not all conditions are met
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    res = client.get(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

# The 'validate' button next to each rule row
def test_condition_validate_rule_row(client, live_server):

    set_original_response("50")

    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("imports.import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data
    wait_for_all_checks(client)

    uuid = next(iter(live_server.app.config['DATASTORE'].data['watching']))

    # the front end submits the current form state which should override the watch in a temporary copy
    res = client.post(
        url_for("conditions.verify_condition_single_rule", watch_uuid=uuid),  # Base URL
        query_string={"rule": json.dumps({"field": "extracted_number", "operator": "==", "value": "50"})},
        data={'include_filter': ""},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'success' in res.data

    # Now a number that does not equal what is found in the last fetch
    res = client.post(
        url_for("conditions.verify_condition_single_rule", watch_uuid=uuid),  # Base URL
        query_string={"rule": json.dumps({"field": "extracted_number", "operator": "==", "value": "111111"})},
        data={'include_filter': ""},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'false' in res.data

    # Now custom filter that exists
    res = client.post(
        url_for("conditions.verify_condition_single_rule", watch_uuid=uuid),  # Base URL
        query_string={"rule": json.dumps({"field": "extracted_number", "operator": "==", "value": "50"})},
        data={'include_filter': ".number-container"},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'success' in res.data

    # Now custom filter that DOES NOT exists
    res = client.post(
        url_for("conditions.verify_condition_single_rule", watch_uuid=uuid),  # Base URL
        query_string={"rule": json.dumps({"field": "extracted_number", "operator": "==", "value": "50"})},
        data={'include_filters': ".NOT-container"},
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'false' in res.data



