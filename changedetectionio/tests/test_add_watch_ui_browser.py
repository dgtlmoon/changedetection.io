#!/usr/bin/env python3
"""The Add-Watch page's browser picker.

The live preview needs a browser that can render screenshots + xpath element data, and
whatever rendered the preview is what the saved watch must check with - otherwise you
visually pick an element with Chrome and the watch then re-checks it with the plain HTTP
client. These tests cover the offered list, the server-side gate, and that the browser
which rendered a parked snapshot wins over the posted form.
"""
import json
import os

from flask import url_for


def _datastore(client):
    return client.application.config.get('DATASTORE')


def test_hidden_without_a_live_preview_browser(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """No capable browser -> the sidebar link is hidden and the route bounces.

    One seam is patched deliberately: has_visual_browser() (page + sidebar gate) and
    default_visual_browser() both resolve through list_visual_browser_choices(), so the
    gate can't disagree with what the picker would have offered.
    """
    from changedetectionio.blueprint.add_watch_ui import browser_config
    monkeypatch.setattr(browser_config, 'list_visual_browser_choices', lambda datastore: [])

    # Sidebar link is not rendered
    res = client.get(url_for('watchlist.index'))
    assert url_for('add_watch_ui.add_watch_ui_index').encode() not in res.data

    # Direct navigation is bounced back to the watch list
    res = client.get(url_for('add_watch_ui.add_watch_ui_index'), follow_redirects=True)
    assert b'name="fetch_backend"' not in res.data
    assert b'needs an interactive browser' in res.data


def test_shown_when_a_live_preview_browser_exists(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """A capable browser -> the sidebar link is offered and the page serves its picker."""
    from changedetectionio.blueprint.add_watch_ui import browser_config
    monkeypatch.setattr(browser_config, 'list_visual_browser_choices',
                        lambda datastore: [('html_webdriver', 'WebDriver Chrome/Javascript')])

    res = client.get(url_for('watchlist.index'))
    assert url_for('add_watch_ui.add_watch_ui_index').encode() in res.data

    res = client.get(url_for('add_watch_ui.add_watch_ui_index'))
    assert res.status_code == 200
    assert b'name="fetch_backend"' in res.data
    assert b'value="html_webdriver"' in res.data
    # The system default resolves to html_requests (no preview), so a real browser is preselected
    assert b'checked' in res.data


def test_browser_picker_lists_only_live_preview_capable(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Capable browsers are offered; the plain HTTP client never is."""
    from changedetectionio.blueprint.add_watch_ui import browser_config

    # html_webdriver is only preview-capable when it resolves to playwright/puppeteer, so
    # pretend it does (a WEBDRIVER_URL-only deployment resolves it to selenium, which can't).
    monkeypatch.setattr(browser_config, 'is_visual_capable',
                        lambda name, datastore: name == 'html_webdriver')

    res = client.get(url_for('add_watch_ui.add_watch_ui_index'))
    assert res.status_code == 200
    assert b'name="fetch_backend"' in res.data
    assert b'value="html_webdriver"' in res.data
    # The plain HTTP client can't render a preview, so it is not an option
    assert b'value="html_requests"' not in res.data
    # The system default resolves to html_requests here, so it is listed but disabled
    assert b'value="system"' in res.data
    assert b'disabled' in res.data


def test_snapshot_refuses_browser_that_cannot_preview(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """/snapshot won't spend a fetch on a browser that produces no screenshot."""
    from changedetectionio.blueprint.add_watch_ui import browser_config
    monkeypatch.setattr(browser_config, 'is_visual_capable', lambda name, datastore: False)

    # Nothing capable, and no explicit browser asked for -> nothing to preview with
    res = client.get(url_for('add_watch_ui.add_watch_ui_snapshot', url='https://example.com'))
    assert res.status_code == 400
    assert b'No interactive browser' in res.data

    # Explicitly asking for a browser that can't preview is refused just the same
    res = client.get(url_for('add_watch_ui.add_watch_ui_snapshot', url='https://example.com',
                             fetch_backend='html_requests'))
    assert res.status_code == 400

    # A made-up name never resolves to a capable fetcher either (real capability lookup here)
    monkeypatch.undo()
    res = client.get(url_for('add_watch_ui.add_watch_ui_snapshot', url='https://example.com',
                             fetch_backend='../../etc/passwd'))
    assert res.status_code == 400
    res = client.get(url_for('add_watch_ui.add_watch_ui_snapshot', url='https://example.com',
                             fetch_backend='os'))
    assert res.status_code == 400


def test_submit_rejects_unknown_fetcher(client, live_server, measure_memory_usage, datastore_path):
    """A posted browser is checked server side, so a doctored form can't pin a junk fetcher."""
    datastore = _datastore(client)
    test_url = url_for('test_endpoint', _external=True)

    for bad in ('os', 'html_requests\n', '{{7*7}}', '../../etc/passwd', 'html_nope'):
        before = len(datastore.data['watching'])
        res = client.post(
            url_for("ui.ui_views.form_quick_watch_add"),
            data={"url": test_url, "fetch_backend": bad},
            follow_redirects=True
        )
        assert res.status_code == 200
        assert b"Watch added" not in res.data
        assert len(datastore.data['watching']) == before, f"{bad!r} should not have created a watch"


def test_submit_still_accepts_any_installed_fetcher(client, live_server, measure_memory_usage, datastore_path):
    """This endpoint is shared with the watch-list quick-add, which may legitimately name a
    backend that can't render a live preview (restock tests add watches with html_requests) -
    only *offering* it on the Add-Watch page is restricted, not adding a watch with it."""
    datastore = _datastore(client)
    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "processor": "restock_diff", "fetch_backend": "html_requests"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    uuid = next(iter(datastore.data['watching']))
    assert datastore.data['watching'][uuid].get('fetch_backend') == 'html_requests'


def test_submit_saves_chosen_browser(client, live_server, measure_memory_usage, datastore_path):
    """The picked browser lands on the watch instead of leaving it on 'system'."""
    datastore = _datastore(client)
    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "fetch_backend": "html_webdriver"},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    uuid = next(iter(datastore.data['watching']))
    assert datastore.data['watching'][uuid].get('fetch_backend') == 'html_webdriver'


def test_parked_snapshot_browser_wins_over_form(client, live_server, measure_memory_usage, datastore_path):
    """The browser that actually rendered the snapshot is the one the watch keeps.

    /snapshot records it in the temporary watch's own watch.json; promoting the snapshot
    must prefer that over whatever the form posted, since the parked screenshot and
    element data came from it.
    """
    datastore = _datastore(client)
    test_url = url_for('test_endpoint', _external=True)

    temp_uuid = '11111111-2222-3333-4444-555555555555'
    temp_dir = datastore.get_temporary_watch_dir(temp_uuid)
    os.makedirs(temp_dir, exist_ok=True)
    with open(os.path.join(temp_dir, "watch.json"), 'w') as f:
        json.dump({"fetch_backend": "html_webdriver"}, f)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "fetch_backend": "html_requests", "temporary_uuid": temp_uuid},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    uuid = next(iter(datastore.data['watching']))
    assert datastore.data['watching'][uuid].get('fetch_backend') == 'html_webdriver'
    # The snapshot dir was promoted into the watch, not left behind
    assert not os.path.isdir(temp_dir)


def test_watchlist_quick_add_is_unaffected(client, live_server, measure_memory_usage, datastore_path):
    """The watch-list quick-add posts no browser at all - that still means 'system'."""
    datastore = _datastore(client)
    test_url = url_for('test_endpoint', _external=True)

    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url},
        follow_redirects=True
    )
    assert b"Watch added" in res.data

    uuid = next(iter(datastore.data['watching']))
    assert datastore.data['watching'][uuid].get('fetch_backend') in (None, '', 'system')
