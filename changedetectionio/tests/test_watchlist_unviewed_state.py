#!/usr/bin/env python3

"""Re #4021 - the "Mark all viewed" button must be driven by live state, not by render-time presence.

The button used to be wrapped in {% if unread_count %}, so when nothing was unread it did not
exist in the DOM at all. A second tab could therefore never show it after a change arrived, and
never hide it after another tab marked everything viewed - no socket event can style an element
that isn't there.

It is now always rendered and revealed by body.has-any-unviewed, which is set server-side via
extra_classes and kept live by the general_stats_update socket event. These assertions pin both
halves: the element is always present, and the body class tracks the unviewed state.
"""

from flask import url_for

from .util import set_original_response, set_modified_response, wait_for_all_checks, delete_all_watches


def _body_has_any_unviewed(res):
    """The <body> class list is what CSS keys off - realtime.js toggles the same class."""
    for line in res.data.decode('utf-8').split('\n'):
        if '<body class="' in line:
            return 'has-any-unviewed' in line
    raise AssertionError("no <body class=...> found in response")


def test_mark_all_viewed_button_is_always_in_the_dom(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)

    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": url_for('test_endpoint', _external=True), "tags": ''},
        follow_redirects=True
    )
    wait_for_all_checks(client)

    # First snapshot only - nothing is unread yet
    res = client.get(url_for("watchlist.index"))
    assert b'id="post-list-mark-views"' in res.data, \
        "Button must be in the DOM even with nothing unread, or another tab can never reveal it"
    assert not _body_has_any_unviewed(res), "Nothing unread, so the body class must be absent"

    # A real change lands -> unviewed
    set_modified_response(datastore_path=datastore_path)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    res = client.get(url_for("watchlist.index"))
    assert b'id="post-list-mark-views"' in res.data
    assert _body_has_any_unviewed(res), "Unviewed change present, so the body class must be set"

    # Mark all viewed runs synchronously (Re #4021), so the redirect must already reflect it
    res = client.get(url_for("ui.mark_all_viewed"), follow_redirects=True)
    assert not _body_has_any_unviewed(res), \
        "mark_all_viewed must be applied before the redirect renders - it used to run in a " \
        "background thread and the page rendered mid-marking"
    assert b'id="post-list-mark-views"' in res.data, "Still in the DOM, just hidden by CSS"
    assert b'class="has-unread-changes' not in res.data

    delete_all_watches(client)
