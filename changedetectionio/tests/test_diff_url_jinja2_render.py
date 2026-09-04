#!/usr/bin/env python3
"""
Regression test for issue #3776.

A watch whose URL contains a Jinja2 template (for example
{% now 'utc', '%Y' %}) must show the Jinja2-rendered, safety-validated URL as
the clickable link on the diff page, not the raw template string.

The diff/preview pages passed the raw watch['url'] into base.html as
current_diff_url, so the "current-diff-url" anchor linked the unrendered
template (non-clickable). Watch.link already does jinja_render() + safe-url
validation, so the pages must use it.
"""

import re
from flask import url_for

from changedetectionio.tests.util import live_server_setup, delete_all_watches
from changedetectionio.jinja2_custom import render as jinja_render


def _add_watch_with_history(app, url):
    """Add a watch and inject two snapshots so the diff page renders without a live fetch."""
    datastore = app.config['DATASTORE']
    # paused: we only need the injected history to render the diff page, no live fetch.
    uuid = datastore.add_watch(url=url, extras={'paused': True})
    watch = datastore.data['watching'][uuid]
    watch.save_history_blob('initial content\n', '1000000000', 'snap-v1')
    watch.save_history_blob('updated content\n', '1000000001', 'snap-v2')
    return uuid


def test_diff_page_links_rendered_jinja2_url(client, live_server, measure_memory_usage, datastore_path):
    live_server_setup(live_server)
    delete_all_watches(client)

    app = client.application

    # A valid URL carrying a Jinja2 template; Watch.link renders and validates it
    # (renders to e.g. https://example.com/data/2026/report.csv).
    jinja_url = "https://example.com/data/{% now 'utc', '%Y' %}/report.csv"
    rendered_url = jinja_render(template_str=jinja_url)
    assert '{% now' not in rendered_url and rendered_url.startswith('https://example.com/data/')

    uuid = _add_watch_with_history(app, jinja_url)

    res = client.get(
        url_for('ui.ui_diff.diff_history_page', uuid=uuid),
        follow_redirects=True,
    )
    assert res.status_code == 200
    html = res.data.decode('utf-8')

    # The diff page must render a clickable current-diff-url anchor,
    m = re.search(r'<a class="current-diff-url" href="([^"]*)"', html)
    assert m, "current-diff-url link not present on the diff page"
    href = m.group(1)

    # and its href must be the rendered URL, never the raw Jinja2 template.
    assert '{% now' not in href, f"diff page still links the raw Jinja2 template: {href}"
    assert href == rendered_url, f"expected rendered URL {rendered_url!r}, got {href!r}"
