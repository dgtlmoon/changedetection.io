#!/usr/bin/env python3
"""End-to-end test for the site_inventory_diff processor.

Goes through the full Flask add-watch → fetch → process → history flow using
the existing live_server harness. Verifies:

* The processor is discoverable and selectable.
* Sitemap-source watches extract URLs correctly and store them as the snapshot.
* Adding a URL to the sitemap between checks is correctly detected as a change.
* CSV export endpoint returns the expected rows.
"""

import os
import time
from flask import url_for

from ..util import live_server_setup, wait_for_all_checks, extract_UUID_from_client


SITEMAP_V1 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
</urlset>"""

SITEMAP_V2 = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/a</loc></url>
  <url><loc>https://example.com/b</loc></url>
  <url><loc>https://example.com/new-page</loc></url>
</urlset>"""


def _write_endpoint_content(datastore_path, body):
    with open(os.path.join(datastore_path, "endpoint-content.txt"), "w") as f:
        f.write(body)


def test_site_inventory_diff_sitemap_e2e(client, live_server, measure_memory_usage, datastore_path):
    _write_endpoint_content(datastore_path, SITEMAP_V1)

    test_url = url_for("test_endpoint", _external=True) + "?content_type=application/xml"

    # Add a watch configured to use the inventory processor.
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": "", "processor": "site_inventory_diff"},
        follow_redirects=True,
    )
    assert res.status_code == 200

    uuid = extract_UUID_from_client(client)

    # Kick the first check and wait.
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # Verify the snapshot contains the two URLs.
    datastore = client.application.config.get("DATASTORE")
    watch = datastore.data["watching"].get(uuid)
    assert watch is not None, "watch disappeared"
    assert watch.get("processor") == "site_inventory_diff"

    assert watch.history, "no history written on first check"
    latest = sorted(watch.history.keys(), key=lambda k: int(k))[-1]
    snap = watch.get_history_snapshot(timestamp=latest)
    assert "https://example.com/a" in snap
    assert "https://example.com/b" in snap
    assert "https://example.com/new-page" not in snap

    # Now mutate the endpoint — add a new URL — and trigger another check.
    _write_endpoint_content(datastore_path, SITEMAP_V2)
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    watch = datastore.data["watching"].get(uuid)
    assert len(watch.history) >= 2, "new history entry should be written after change"
    latest = sorted(watch.history.keys(), key=lambda k: int(k))[-1]
    snap = watch.get_history_snapshot(timestamp=latest)
    assert "https://example.com/new-page" in snap

    # --- Dashboard and CSV endpoints should respond ---------------------
    res = client.get(url_for("site_inventory.dashboard"), follow_redirects=True)
    assert res.status_code == 200
    assert b"Site URL inventory" in res.data or b"site-inventory-fieldset" in res.data or b"Watch" in res.data

    res = client.get(url_for("site_inventory.csv_export", uuid=uuid))
    assert res.status_code == 200
    assert res.mimetype == "text/csv"
    body = res.data.decode("utf-8")
    # The new page should appear as status=added in the CSV.
    assert "https://example.com/new-page" in body
    assert "added" in body
