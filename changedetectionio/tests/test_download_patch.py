#!/usr/bin/env python3
"""
Tests for the /diff/<uuid>/download-patch endpoint.

The route should accept from_version and to_version query parameters,
read those two snapshots from the watch history, generate a unified diff
patch, and return it as a downloadable text/plain file.
"""

from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches, wait_for_all_checks


def _add_watch_with_history(app, url, v1_text, v2_text):
    """
    Add a watch and inject two synthetic snapshots into its history so we
    can test the download-patch route without hitting a live fetch cycle.
    """
    datastore = app.config['DATASTORE']
    uuid = datastore.add_watch(url=url, extras={})
    watch = datastore.data['watching'][uuid]

    # Write the two snapshots directly via save_history_blob
    # Args: contents (str), timestamp (str), snapshot_id (str)
    watch.save_history_blob(v1_text, '1000000000', 'snap-v1')
    watch.save_history_blob(v2_text, '1000000001', 'snap-v2')

    return uuid


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_download_patch_returns_unified_diff(client, live_server, measure_memory_usage, datastore_path):
    """
    The endpoint should return a .patch file whose content is a valid unified
    diff between the two requested snapshots.
    """
    live_server_setup(live_server)
    delete_all_watches(client)

    app = client.application
    test_url = url_for('test_endpoint', content_type='text/html', content='hello', _external=True)

    v1 = 'line one\nline two\nline three\n'
    v2 = 'line one\nline two modified\nline three\nline four\n'

    uuid = _add_watch_with_history(app, test_url, v1, v2)

    res = client.get(
        url_for('ui.ui_diff.download_patch', uuid=uuid,
                from_version='1000000000', to_version='1000000001'),
        follow_redirects=True,
    )

    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.data[:200]}"
    assert 'text/plain' in res.headers.get('Content-Type', '')
    # No forced download — should open inline in the browser
    assert 'attachment' not in res.headers.get('Content-Disposition', '')

    patch = res.data.decode('utf-8')
    assert '---' in patch or '+' in patch, "Response should contain unified diff markers"
    assert 'line two modified' in patch or '+line two modified' in patch
    assert '-line two' in patch


def test_download_patch_link_present_in_diff_page(client, live_server, measure_memory_usage, datastore_path):
    """
    The diff history page HTML should contain a 'Download difference patch' link
    pointing to the download-patch route when from_version and to_version are set.
    """
    live_server_setup(live_server)
    delete_all_watches(client)

    app = client.application
    test_url = url_for('test_endpoint', content_type='text/html', content='initial content', _external=True)

    uuid = _add_watch_with_history(app, test_url, 'initial content\n', 'updated content\n')

    # Load the diff page without explicit versions — should default to last two
    res = client.get(
        url_for('ui.ui_diff.diff_history_page', uuid=uuid),
        follow_redirects=True,
    )

    assert res.status_code == 200
    html = res.data.decode('utf-8')
    assert 'Download difference patch' in html
    assert 'download-patch' in html


def test_download_patch_unknown_uuid_returns_404(client, live_server, measure_memory_usage, datastore_path):
    """
    Requesting a patch for a non-existent watch should return 404.
    """
    live_server_setup(live_server)
    delete_all_watches(client)

    res = client.get(
        url_for('ui.ui_diff.download_patch', uuid='00000000-0000-0000-0000-000000000000',
                from_version='1000000000', to_version='1000000001'),
    )

    assert res.status_code == 404
