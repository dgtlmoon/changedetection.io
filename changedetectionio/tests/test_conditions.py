#!/usr/bin/env python3

import time
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

def test_setup(live_server):
    live_server_setup(live_server)

def test_number_within_range_condition(client, live_server, measure_memory_usage):
    set_original_response()
#    live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Configure the watch with two conditions:
    # 1. The extracted number should be >= 20 and <= 100
    # 2. The first digit of the number should be in the page filtered text
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "include_filters": ".number-container",
            "title": "Condition Test",
            "conditions_match_logic": "ALL",  # ALL = AND logic
            "conditions": [
                {"operator": ">=", "field": "extracted_number", "value": "20"},
                {"operator": "<=", "field": "extracted_number", "value": "100"},
                {"operator": "in", "field": "page_filtered_text", "value": "5"}  # First digit of 50
            ]
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Trigger initial check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Set current view state - no unviewed
    client.get(url_for("diff_history_page", uuid="first"))

    # Change that stays within the conditions (number is in range and text contains first digit)
    set_number_in_range_response("75")  
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should NOT be marked as having changes since it meets all conditions
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data
    assert b'Condition Test' in res.data

    # Now change to value that's outside the range (but still contains the first digit in text)
    set_number_out_of_range_response("150")
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # SHOULD be marked as having changes since it violates one of the conditions
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
    assert b'Condition Test' in res.data

    # Check the diff history shows the change
    res = client.get(url_for("diff_history_page", uuid="first"))
    assert b'Current value: 150' in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data

def test_conditions_with_text_and_number(client, live_server, measure_memory_usage):
    """Test that both text and number conditions work together with AND logic."""
    
    set_original_response("50")
    #live_server_setup(live_server)

    test_url = url_for('test_endpoint', _external=True)

    # Add our URL to the import page
    res = client.post(
        url_for("import_page"),
        data={"urls": test_url},
        follow_redirects=True
    )
    assert b"1 Imported" in res.data

    # Configure the watch with two conditions connected with AND:
    # 1. The page filtered text must contain "5" (first digit of value)
    # 2. The extracted number should be >= 20 and <= 100
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "include_filters": ".number-container",
            "title": "Number AND Text Condition Test",
            "conditions_match_logic": "ALL",  # ALL = AND logic
            "conditions": [
                {"operator": "in", "field": "page_filtered_text", "value": "5"},  # First digit of 50
                {"operator": ">=", "field": "extracted_number", "value": "20"},
                {"operator": "<=", "field": "extracted_number", "value": "100"}
            ]
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data

    # Trigger initial check
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Set current view state - no unviewed
    client.get(url_for("diff_history_page", uuid="first"))

    # Case 1: The number is in range but the first digit changed (now 7 instead of 5)
    # This should trigger a change notification since the text condition is violated
    set_number_in_range_response("75")
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Should be marked as having changes since it violates the text condition
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data
    
    # Reset view state
    client.get(url_for("diff_history_page", uuid="first"))

    # Case 2: Change with both conditions satisfied
    # Number in range (80) and contains first digit "8" in text
    set_number_in_range_response("80")
    
    # Update the conditions to match the new value's first digit
    res = client.post(
        url_for("edit_page", uuid="first"),
        data={
            "url": test_url,
            "fetch_backend": "html_requests",
            "include_filters": ".number-container",
            "title": "Number AND Text Condition Test",
            "conditions_match_logic": "ALL",  # ALL = AND logic
            "conditions": [
                {"operator": "in", "field": "page_filtered_text", "value": "8"},  # First digit of 80
                {"operator": ">=", "field": "extracted_number", "value": "20"},
                {"operator": "<=", "field": "extracted_number", "value": "100"}
            ]
        },
        follow_redirects=True
    )
    assert b"Updated watch." in res.data
    
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    
    # Should NOT be marked as having changes since both conditions are met
    res = client.get(url_for("index"))
    assert b'unviewed' not in res.data

    # Case 3: Change with both conditions violated
    # Number out of range (150) and first digit doesn't match condition
    set_number_out_of_range_response("150")
    client.get(url_for("form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # SHOULD be marked as having changes since both conditions are violated
    res = client.get(url_for("index"))
    assert b'unviewed' in res.data

    res = client.get(url_for("form_delete", uuid="all"), follow_redirects=True)
    assert b'Deleted' in res.data