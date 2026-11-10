#!/usr/bin/env python3
"""Tests for named browser configs (browsers.json) and the watch-level Browser picker."""
import os
import time
import pytest
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


@pytest.fixture(autouse=True)
def html_webdriver_is_playwright(monkeypatch):
    """These tests use html_webdriver as "a full browser". Without a Playwright driver URL it
    resolves to Selenium, which doesn't apply a profile's screen size / locale / timezone
    (supports_page_settings), so pin it to the Playwright engine. Nothing here connects to it."""
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
    monkeypatch.setattr(content_fetchers, 'html_webdriver', playwright_fetcher)


def _add_browser(client, label="Mobile de-DE", base_fetcher="html_webdriver", **cfg):
    # Add via the per-base "Add variation" route (base is in the URL, not the form).
    data = {'label': label}
    data.update(cfg)
    return client.post(url_for("ui.browser_config.browser_config_add", base_fetcher=base_fetcher),
                       data=data, follow_redirects=True)


def _wait_for_debug_snapshot(client, datastore, uuid, timeout=15):
    """Check the watch and return its latest snapshot once the debug fetcher has written one.

    Waits for the debug fetcher's own marker rather than just "has a snapshot", so a snapshot from
    some other fetch can't satisfy it. Re-requests the check while waiting in case the first
    request was skipped because the scheduler already had the watch queued.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        watch = datastore.data['watching'][uuid]
        if watch.history_n:
            snapshot = watch.get_history_snapshot(timestamp=watch.newest_history_key)
            if 'debug_test_browser' in snapshot:
                return snapshot
        time.sleep(0.2)
    raise AssertionError(f"No snapshot from the debug fetcher within {timeout}s")


@pytest.mark.skipif(not os.getenv('ENABLE_DEBUG_CONTENT_FETCHER'),
                    reason="Needs ENABLE_DEBUG_CONTENT_FETCHER (set in the test-browser-config CI step)")
def test_debug_content_fetcher_pipeline(client, live_server, measure_memory_usage, datastore_path):
    """End-to-end: prove a browser config's FetcherConfig actually reaches the fetcher.

    Uses the debug fetcher (ENABLE_DEBUG_CONTENT_FETCHER, set in conftest), which echoes the
    injected browser_config as JSON content - so a real watch check exercises the whole
    resolve -> select engine -> inject FetcherConfig -> fetch pipeline, with no real browser.
    """
    datastore = client.application.config.get('DATASTORE')

    # Add the browser variation through the real Add flow (per-base route + form), not the store
    res = _add_browser(client, label="Debug pipeline", base_fetcher="html_debug_test_browser",
                       locale='de-DE', timezone_id='Europe/Berlin',
                       viewport_width=1234, viewport_height=567, browser_type='firefox')
    assert b"Debug pipeline" in res.data
    cid = list(datastore.browser_config_store.all())[0]

    # Set the browser when the watch is created: the scheduler can check a brand-new watch straight
    # away, and setting fetch_backend afterwards raced it (fetched with the default browser, and the
    # "check now" below was skipped because the watch was already queued)
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': cid})
    _wait_for_debug_snapshot(client, datastore, uuid)

    res = client.get(url_for("ui.ui_preview.preview_page", uuid=uuid), follow_redirects=True)
    # The debug fetcher echoed the resolved browser_config + capabilities into the snapshot
    assert b'html_debug_test_browser' in res.data   # engine resolved from the browser config
    assert b'firefox' in res.data                    # resolved sub-browser (browser_type)
    assert b'de-DE' in res.data                      # locale
    assert b'Europe/Berlin' in res.data              # timezone
    assert b'1234' in res.data                       # viewport
    assert b'supports_screenshots' in res.data       # capabilities reported
    # The browser supports screenshots, so the preview must NOT show the "requires a fetcher that
    # supports screenshots" message (capability resolved via the config, not the watch's backend).
    assert b'that supports screenshots' not in res.data


def _recheck_and_get_snapshot(client, datastore, uuid, timeout=30):
    """Check the watch once more and return its newest snapshot, for a check that STARTED after
    this call - so it ran with whatever the test changed just before calling.

    last_checked is the check's start time rounded to a second, so wait two seconds out from now
    and only accept a check stamped at or after that: one started before the change (the scheduler
    may have had the watch queued) can't satisfy it, even rounded up.
    """
    started_after = int(time.time()) + 2
    while time.time() < started_after:
        time.sleep(0.1)
    deadline = time.time() + timeout
    while time.time() < deadline:
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        watch = datastore.data['watching'][uuid]
        if (watch.get('last_checked') or 0) >= started_after and watch.history_n:
            return watch.get_history_snapshot(timestamp=watch.newest_history_key)
        time.sleep(0.2)
    raise AssertionError(f"Watch {uuid} was not checked again within {timeout}s")


def _set_group_override(client, datastore, tag_uuid, browser_id, enabled):
    """Set a group's browser override through its edit form, as a user would."""
    title = datastore.data['settings']['application']['tags'][tag_uuid]['title']
    data = {'title': title, 'browser_config': browser_id}
    if enabled:
        data['browser_config_overrides_watch'] = 'y'
    client.post(url_for("tags.form_tag_edit_submit", uuid=tag_uuid), data=data, follow_redirects=True)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    assert bool(tag.get('browser_config_overrides_watch')) is enabled
    assert tag.get('browser_config') == browser_id


def _watchlist_row(client, uuid):
    import re
    html = client.get(url_for("watchlist.index")).data.decode()
    return re.search(rf'<tr id="{uuid}".*?</tr>', html, re.S).group(0)


@pytest.mark.skipif(not os.getenv('ENABLE_DEBUG_CONTENT_FETCHER'),
                    reason="Needs ENABLE_DEBUG_CONTENT_FETCHER (set in the test-browser-config CI step)")
def test_group_override_decides_the_browser_at_fetch_time(client, live_server, measure_memory_usage, datastore_path):
    """End-to-end, with real checks: the browser a watch is FETCHED with follows the whole chain -
    group override (first group in the watch's order) -> the watch's own choice -> system default -
    and the watch list shows that same browser's icon at every step.

    The debug fetcher echoes what it was handed into the snapshot, so each step reads back the
    browser the worker actually used rather than what a resolver says it would use.
    """
    from .util import set_original_response
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    # What the plain HTTP client gets from the test endpoint, for the steps where it is the one fetching
    set_original_response(datastore_path=datastore_path)

    _add_browser(client, label="French phone", base_fetcher="html_debug_test_browser",
                 browser_type='firefox', locale='fr-FR', viewport_width=375, viewport_height=812)
    _add_browser(client, label="Japanese desktop", base_fetcher="html_debug_test_browser",
                 browser_type='webkit', locale='ja-JP')
    ids = {e['label']: cid for cid, e in datastore.browser_config_store.all().items()}
    french, japanese = ids['French phone'], ids['Japanese desktop']

    def _fetched_with(snapshot):
        """Which of the two browsers produced this snapshot, or None for anything else."""
        if 'debug_test_browser' not in snapshot:
            return None
        assert '"backend_name": "html_debug_test_browser"' in snapshot
        if '"locale": "fr-FR"' in snapshot:
            # The whole variation arrived, not just its name
            assert '"browser_type": "firefox"' in snapshot
            assert '"viewport_width": 375' in snapshot
            return french
        assert '"locale": "ja-JP"' in snapshot and '"browser_type": "webkit"' in snapshot
        return japanese

    # Two groups, the first overriding to the French phone - set up before the watch exists so
    # its very first check already runs under the override
    group_a = datastore.add_tag("Group A")
    group_b = datastore.add_tag("Group B")
    _set_group_override(client, datastore, group_a, french, enabled=True)

    # The watch itself asks for the plain HTTP client
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), tag_uuids=[group_a],
                               extras={'fetch_backend': 'html_requests'})
    watch = datastore.data['watching'][uuid]
    assert watch.get('fetch_backend') == 'html_requests'

    # 1. The group's browser fetched it, not the watch's own
    assert _fetched_with(_wait_for_debug_snapshot(client, datastore, uuid)) == french
    row = _watchlist_row(client, uuid)
    assert 'firefox-icon.svg' in row
    assert 'French phone (firefox) — from group Group A' in row

    # 2. A second overriding group AFTER the first in the watch's order changes nothing
    _set_group_override(client, datastore, group_b, japanese, enabled=True)
    watch['tags'] = [group_a, group_b]
    assert _fetched_with(_recheck_and_get_snapshot(client, datastore, uuid)) == french
    assert 'firefox-icon.svg' in _watchlist_row(client, uuid)

    # 3. ...but first in the order, it is the one that wins
    watch['tags'] = [group_b, group_a]
    assert _fetched_with(_recheck_and_get_snapshot(client, datastore, uuid)) == japanese
    row = _watchlist_row(client, uuid)
    assert 'webkit-icon.svg' in row and 'firefox-icon.svg' not in row
    assert 'from group Group B' in row

    # 4. Its override switched off: the next group in line takes over
    _set_group_override(client, datastore, group_b, japanese, enabled=False)
    assert _fetched_with(_recheck_and_get_snapshot(client, datastore, uuid)) == french
    assert 'firefox-icon.svg' in _watchlist_row(client, uuid)

    # 5. No override left: back to the watch's own choice, the plain client (no browser icon)
    _set_group_override(client, datastore, group_a, french, enabled=False)
    snapshot = _recheck_and_get_snapshot(client, datastore, uuid)
    assert _fetched_with(snapshot) is None, f"still fetched by a group's browser - last error: {watch.get('last_error')}"
    assert 'Some initial text' in snapshot, "the plain client fetched the real page"
    row = _watchlist_row(client, uuid)
    for icon in ('firefox-icon.svg', 'webkit-icon.svg', 'google-chrome-icon.png', 'playwright-icon.png'):
        assert icon not in row
    assert 'from group' not in row

    # 6. Following the system default: whatever /settings/browsers sets as the default is what fetches
    watch['fetch_backend'] = 'system'
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=japanese), follow_redirects=True)
    assert _fetched_with(_recheck_and_get_snapshot(client, datastore, uuid)) == japanese
    assert 'webkit-icon.svg' in _watchlist_row(client, uuid)

    # 7. And a group override still beats the system default
    _set_group_override(client, datastore, group_a, french, enabled=True)
    assert _fetched_with(_recheck_and_get_snapshot(client, datastore, uuid)) == french
    assert 'firefox-icon.svg' in _watchlist_row(client, uuid)


def test_group_override_order_off_switch_and_missing_browser(client, live_server, measure_memory_usage, datastore_path):
    """The override rules themselves (Watch.get_fetch_backend), and the watch list icon that
    follows them, without fetching anything - so it runs everywhere, unlike the end-to-end test
    above: the first overriding group in the watch's order wins, a group with its override off or
    pointing at a browser that no longer exists is skipped, and with none left the watch's own
    choice is back."""
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    tags = datastore.data['settings']['application']['tags']

    _add_browser(client, label="Group browser", viewport_width=1111, viewport_height=700)
    group_browser = next(iter(datastore.browser_config_store.all()))

    first = datastore.add_tag("First group")
    second = datastore.add_tag("Second group")
    _set_group_override(client, datastore, first, group_browser, enabled=True)
    _set_group_override(client, datastore, second, 'html_webdriver', enabled=True)

    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': 'html_requests', 'paused': True})
    watch = datastore.data['watching'][uuid]

    def _resolved():
        """(selector the watch resolves to, engine + viewport the fetcher would really get)"""
        _cls, engine, _url, config = resolve_content_fetcher(watch, datastore)
        return watch.get_fetch_backend, engine, config.viewport_width

    # No group: the watch's own choice
    assert _resolved() == ('html_requests', 'html_requests', None)
    assert 'google-chrome-icon.png' not in _watchlist_row(client, uuid)

    # First in the watch's order wins, with its settings
    watch['tags'] = [first, second]
    assert _resolved() == (group_browser, 'html_webdriver', 1111)
    row = _watchlist_row(client, uuid)
    assert 'google-chrome-icon.png' in row and 'Group browser — from group First group' in row

    watch['tags'] = [second, first]
    assert _resolved() == ('html_webdriver', 'html_webdriver', None)
    assert 'from group Second group' in _watchlist_row(client, uuid)

    # An override that is switched off is skipped, the next group's applies
    _set_group_override(client, datastore, second, 'html_webdriver', enabled=False)
    assert _resolved() == (group_browser, 'html_webdriver', 1111)
    assert 'from group First group' in _watchlist_row(client, uuid)

    # So is one whose browser no longer exists - it must not break the watch
    tags[second]['browser_config_overrides_watch'] = True
    tags[second]['browser_config'] = 'a-browser-that-was-removed'
    assert _resolved() == (group_browser, 'html_webdriver', 1111)

    # None left: the watch's own choice again, and no browser icon
    _set_group_override(client, datastore, first, group_browser, enabled=False)
    tags[second]['browser_config_overrides_watch'] = False
    assert _resolved() == ('html_requests', 'html_requests', None)
    row = _watchlist_row(client, uuid)
    assert 'google-chrome-icon.png' not in row and 'from group' not in row


def test_browser_config_crud(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')

    # Empty state: no configs, but the overview renders
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert res.status_code == 200

    # Add one
    res = _add_browser(client, label="Desktop Full-HD", viewport_width=1920, viewport_height=1080,
                       locale="en-GB", timezone_id="Europe/London")
    assert b"Desktop Full-HD" in res.data
    configs = datastore.browser_config_store.all()
    assert len(configs) == 1
    cid = list(configs)[0]
    assert configs[cid]['browser_config']['locale'] == 'en-GB'
    assert configs[cid]['browser_config']['viewport_width'] == 1920

    # The variation renders nested (↳) under its base browser row, not in a separate table
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert b"browser-variation-row" in res.data
    assert b"Desktop Full-HD" in res.data
    assert b"Your browsers" not in res.data  # the old separate table is gone

    # Invalid locale is rejected with an inline error, nothing stored
    res = _add_browser(client, label="Bad", locale="xx-ZZ")
    assert b"Unknown locale" in res.data
    assert len(datastore.browser_config_store.all()) == 1

    # A name is required
    res = _add_browser(client, label="")
    assert len(datastore.browser_config_store.all()) == 1

    # Set default -> becomes the global system fetch_backend (single source of truth)
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)
    assert datastore.data['settings']['application']['fetch_backend'] == cid

    # Edit
    res = client.post(url_for("ui.browser_config.browser_config_edit", config_id=cid),
                      data={'label': 'Desktop 4K', 'base_fetcher': 'html_webdriver',
                            'viewport_width': 3840, 'viewport_height': 2160, 'screenshot_format': 'JPEG'},
                      follow_redirects=True)
    assert b"Desktop 4K" in res.data
    assert datastore.browser_config_store.get(cid)['browser_config']['viewport_width'] == 3840

    # Remove - refused while it is still the default browser (see test_remove_refused_while_in_use)
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    client.post(url_for("ui.browser_config.browser_config_remove", config_id=cid), follow_redirects=True)
    assert len(datastore.browser_config_store.all()) == 0


def test_remove_refused_while_in_use(client, live_server, measure_memory_usage, datastore_path):
    """A browser that a watch, a group override or the system default still points at can't be
    removed - the watches left behind could no longer be checked (BrowserConfigDoesntExist).
    The refusal links to the watch list filtered to the watches that use it."""
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, label="In use")
    cid = next(iter(datastore.browser_config_store.all()))
    remove_url = url_for("ui.browser_config.browser_config_remove", config_id=cid)
    watches_url = url_for("watchlist.index", browser=cid)

    def _remove():
        return client.post(remove_url, follow_redirects=True)

    # The default browser
    datastore.data['settings']['application']['fetch_backend'] = cid
    assert b"This is the default browser" in _remove().data
    assert datastore.browser_config_store.get(cid)
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'

    # Chosen by a watch
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': cid})
    res = _remove()
    assert b"still in use (watches: 1, groups: 0)" in res.data
    assert f'<a href="{watches_url}">'.encode() in res.data, "the refusal links to that browser's watches"
    assert datastore.browser_config_store.get(cid)
    # ...and the page offers no working Remove for it, only the count
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert b'browser-chip--usage' in res.data
    assert f'action="{remove_url}"'.encode() not in res.data
    datastore.data['watching'][uuid]['fetch_backend'] = 'system'

    # Chosen by a group override - only while the override is switched on. The watch in that
    # group counts too: it reaches the browser through the group.
    tag_uuid = datastore.add_tag(title="Shops")
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    tag['browser_config'] = cid
    tag['browser_config_overrides_watch'] = True
    datastore.data['watching'][uuid]['tags'] = [tag_uuid]
    assert b"still in use (watches: 1, groups: 1)" in _remove().data
    assert datastore.browser_config_store.get(cid)
    tag['browser_config_overrides_watch'] = False

    # Nothing uses it any more
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert f'action="{remove_url}"'.encode() in res.data
    assert b"Browser config removed" in _remove().data
    assert not datastore.browser_config_store.get(cid)


def test_watchlist_filter_by_browser(client, live_server, measure_memory_usage, datastore_path):
    """/?browser=<id> lists the watches that use that browser whichever level chose it - the
    watch itself, a group override or the system default - and its count on /settings/browsers agrees."""
    from changedetectionio.blueprint.watchlist.filters import matching_watch_uuids
    from changedetectionio.model.browser_config import browser_config_usage
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    _add_browser(client, label="Filter me")
    cid = next(iter(datastore.browser_config_store.all()))
    test_url = url_for('test_endpoint', _external=True)

    def _matching(browser):
        return set(matching_watch_uuids(datastore, {'browser': browser}))

    direct = datastore.add_watch(url=test_url, extras={'fetch_backend': cid})
    via_group = datastore.add_watch(url=test_url, extras={'fetch_backend': 'html_requests'})
    via_default = datastore.add_watch(url=test_url, extras={'fetch_backend': 'system'})
    other = datastore.add_watch(url=test_url, extras={'fetch_backend': 'html_requests'})

    # 1. Only the watch that chose it itself
    assert _matching(cid) == {direct}
    assert _matching('html_requests') == {via_group, via_default, other}
    assert len(_matching('')) == 4, "no browser filter, every watch"

    # 2. A group override pulls its watch in - and that watch still lists under the browser it
    #    chose itself, which it falls back to when the override goes
    tag_uuid = datastore.add_tag(title="Overriders")
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    tag['browser_config'] = cid
    tag['browser_config_overrides_watch'] = True
    datastore.data['watching'][via_group]['tags'] = [tag_uuid]
    assert _matching(cid) == {direct, via_group}
    assert via_group in _matching('html_requests')

    # ...but not while the group's override is switched off
    tag['browser_config_overrides_watch'] = False
    assert _matching(cid) == {direct}
    tag['browser_config_overrides_watch'] = True

    # 3. As the system default, the watches that follow the default come too
    datastore.data['settings']['application']['fetch_backend'] = cid
    assert _matching(cid) == {direct, via_group, via_default}
    assert _matching('html_requests') == {via_group, other}

    # The count on /settings/browsers is the same set
    assert browser_config_usage(datastore)[cid] == {'watches': 3, 'groups': 1}

    # The rendered list: the three rows, the browser named, and a way back out
    res = client.get(url_for("watchlist.index", browser=cid))
    for uuid in (direct, via_group, via_default):
        assert f'data-watch-uuid="{uuid}"'.encode() in res.data
    assert f'data-watch-uuid="{other}"'.encode() not in res.data
    assert b'id="browser-filter-info"' in res.data
    assert b'Filter me' in res.data


def test_custom_size_needs_a_width_and_a_height(client, live_server, measure_memory_usage, datastore_path):
    """The device picker offers "Desktop (default size)" and "Custom size" apart: choosing a
    custom size without giving one is refused, the default size stores no viewport at all, and a
    saved custom size comes back selected."""
    datastore = client.application.config.get('DATASTORE')
    add_url = url_for("ui.browser_config.browser_config_add", base_fetcher='html_webdriver')

    form_html = client.get(add_url).data.decode()
    assert '<option selected value="">Desktop (default size)</option>' in form_html
    assert '<option value="custom">Custom size</option>' in form_html

    def _viewport_of(label):
        entry = next(e for e in datastore.browser_config_store.all().values() if e['label'] == label)
        return entry['browser_config']['device'], entry['browser_config']['viewport_width'], entry['browser_config']['viewport_height']

    # Custom size with nothing, or only half of it: refused, on the field that is missing
    for partial in ({}, {'viewport_width': 1280}, {'viewport_height': 720}):
        res = client.post(add_url, data={'label': 'Custom', 'device': 'custom', **partial}, follow_redirects=True)
        assert b'A custom size needs a width and a height' in res.data
        assert not datastore.browser_config_store.all()

    # With both: stored as a plain viewport - "custom" itself is never a device
    client.post(add_url, data={'label': 'Custom', 'device': 'custom', 'viewport_width': 1280, 'viewport_height': 720},
                follow_redirects=True)
    assert _viewport_of('Custom') == (None, 1280, 720)
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e['label'] == 'Custom')
    edit_html = client.get(url_for("ui.browser_config.browser_config_edit", config_id=cid)).data.decode()
    assert '<option selected value="custom">Custom size</option>' in edit_html
    # The form names the browser it is based on by its own name, not its internal id
    based_on = edit_html[edit_html.index('browser-based-on'):][:300]
    assert 'html_webdriver' not in based_on
    assert str(dict(__import__('changedetectionio').content_fetchers.available_fetchers())['html_webdriver']) in __import__('html').unescape(based_on)
    assert 'value="1280"' in edit_html

    # Default size: no viewport is kept, even if the (hidden) fields still carried one
    client.post(add_url, data={'label': 'Default size', 'device': '', 'viewport_width': 1280, 'viewport_height': 720},
                follow_redirects=True)
    # (a posted empty device is the picker saying "default size")
    assert _viewport_of('Default size') == (None, None, None)

    # A device: its own size, the typed one is dropped
    client.post(add_url, data={'label': 'Phone', 'device': 'Pixel 7', 'viewport_width': 1280, 'viewport_height': 720},
                follow_redirects=True)
    assert _viewport_of('Phone') == ('Pixel 7', None, None)

    # No device picker in the POST at all (a browser that can't emulate devices, an API-style
    # client): the viewport stands by itself and stays optional
    client.post(add_url, data={'label': 'Just a viewport', 'viewport_width': 1024, 'viewport_height': 768}, follow_redirects=True)
    assert _viewport_of('Just a viewport') == (None, 1024, 768)
    client.post(add_url, data={'label': 'Nothing set'}, follow_redirects=True)
    assert _viewport_of('Nothing set') == (None, None, None)


def test_browser_form_as_dialog(client, live_server, measure_memory_usage, datastore_path):
    """The /settings/browsers page opens Add variation / Edit in a dialog: the same routes with ?modal=1
    answer with just the form, a failed save comes back as that form with its errors, and a
    successful one as JSON pointing back at the overview."""
    datastore = client.application.config.get('DATASTORE')
    overview_url = url_for("ui.browser_config.browsers_overview")
    add_url = url_for("ui.browser_config.browser_config_add", base_fetcher='html_requests')

    # The overview carries the dialog and marks the links that open in it
    res = client.get(overview_url)
    assert b'id="browser-config-dialog"' in res.data
    assert b'browser-config-modal.js' in res.data
    assert f'<a data-browser-config-modal class="browser-add-variation" href="{add_url}">'.encode() in res.data

    # GET: only the form, posting back to the modal variant - no page around it
    res = client.get(add_url, query_string={'modal': '1'})
    assert res.status_code == 200
    assert b'<html' not in res.data
    assert b'class="modal-header"' in res.data
    assert f'action="{add_url}?modal=1"'.encode() in res.data
    assert b'name="user_agent"' in res.data
    # Same tabs as the page, as buttons naming the pane they show (html_requests has no
    # language/timezone settings, so no such tab)
    assert b'role="tab" data-pane="browser"' in res.data
    assert b'role="tab" data-pane="request"' in res.data
    assert b'data-pane="language"' not in res.data
    assert b'id="request"' in res.data

    # A browser with a timezone setting offers to fill in the user's own (the script names it).
    # Needs the debug fetcher, the one browser every environment can offer with that setting.
    from changedetectionio import content_fetchers
    if hasattr(content_fetchers, 'html_debug_test_browser') and 'html_debug_test_browser' in dict(content_fetchers.available_fetchers()):
        res = client.get(url_for("ui.browser_config.browser_config_add", base_fetcher='html_debug_test_browser'),
                         query_string={'modal': '1'})
        assert b'role="tab" data-pane="language"' in res.data
        assert b'id="use-my-timezone"' in res.data
        assert b'Use my current timezone' in res.data

    # ...while without ?modal=1 it is still the full page
    assert b'<html' in client.get(add_url).data

    # POST with a problem: the form again, with the error, nothing stored and no redirect
    res = client.post(add_url, query_string={'modal': '1'}, data={'label': ''})
    assert res.status_code == 200
    assert b'<html' not in res.data
    assert b'Give this browser config a name' in res.data
    assert not datastore.browser_config_store.all()

    # POST that saves: JSON, and the flash waits for the overview
    res = client.post(add_url, query_string={'modal': '1'}, data={'label': 'From dialog', 'user_agent': 'dialog-agent'})
    assert res.is_json and res.get_json() == {'ok': True, 'redirect': overview_url}
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == 'From dialog')
    assert b'Browser added' in client.get(overview_url).data

    # Edit works the same way
    edit_url = url_for("ui.browser_config.browser_config_edit", config_id=cid)
    res = client.get(edit_url, query_string={'modal': '1'})
    assert b'<html' not in res.data
    assert b'value="dialog-agent"' in res.data
    res = client.post(edit_url, query_string={'modal': '1'}, data={'label': 'From dialog', 'user_agent': 'edited-agent'})
    assert res.get_json() == {'ok': True, 'redirect': overview_url}
    assert datastore.browser_config_store.get(cid)['browser_config']['user_agent'] == 'edited-agent'


def test_browser_config_unique_label(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="Mobile")
    assert len(datastore.browser_config_store.all()) == 1

    # Same label (case-insensitive) is rejected, nothing added
    res = _add_browser(client, label="  mobile ")
    assert b"already exists" in res.data
    assert len(datastore.browser_config_store.all()) == 1


def test_watch_browser_picker_and_resolution(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="Mobile de-DE", viewport_width=390, viewport_height=844,
                 locale="de-DE", timezone_id="Europe/Berlin")
    cid = list(datastore.browser_config_store.all())[0]

    uuid = datastore.add_watch(url="https://example.com")
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    # Picker shows Default, the always-present built-in engines, and our user browser
    assert b"Mobile de-DE" in res.data
    assert b"Default (system settings)" in res.data
    assert b'value="html_webdriver"' in res.data  # built-in engine browser always present
    # There must be exactly one "system" option (no duplicate legacy 'System settings default')
    assert b"System settings default" not in res.data
    assert res.data.count(b'value="system"') == 1
    # No group override, so the normal picker is shown (not the override message)
    assert b"fetch-backend-group-override" not in res.data

    # Selecting the browser stores its id in fetch_backend
    client.post(url_for("ui.ui_edit.edit_page", uuid=uuid),
                data={'url': 'https://example.com', 'fetch_backend': cid, 'processor': 'text_json_diff',
                      'time_between_check_use_default': 'y', 'headers': '', 'method': 'GET', 'tags': ''},
                follow_redirects=True)
    assert datastore.data['watching'][uuid]['fetch_backend'] == cid

    # Watchlist renders fine for a watch whose fetch_backend is a browser-config id - the
    # status icon resolves to the underlying base engine (html_webdriver) as before.
    assert client.get(url_for("watchlist.index")).status_code == 200

    # Resolver maps the browser id -> engine + FetcherConfig
    _cls, backend_name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert backend_name == 'html_webdriver'
    assert browser_config.locale == 'de-DE'
    assert browser_config.viewport_width == 390


def test_edit_builtin_browser_config(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')

    # The built-in html_webdriver is editable; its config is stored keyed by the engine name
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_webdriver"))
    assert res.status_code == 200

    client.post(url_for("ui.browser_config.browser_config_edit", config_id="html_webdriver"),
                data={'label': 'anything', 'base_fetcher': 'html_webdriver', 'viewport_width': 1280,
                      'viewport_height': 720, 'locale': 'it-IT', 'screenshot_format': 'JPEG'},
                follow_redirects=True)
    entry = datastore.browser_config_store.get('html_webdriver')
    assert entry is not None
    assert entry['base_fetcher'] == 'html_webdriver'
    assert entry['browser_config']['locale'] == 'it-IT'

    # A watch using the html_webdriver engine picks up that stored built-in config
    uuid = datastore.add_watch(url="https://example.com")
    datastore.data['watching'][uuid]['fetch_backend'] = 'html_webdriver'
    _cls, name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert name == 'html_webdriver'
    assert browser_config.locale == 'it-IT'
    assert browser_config.viewport_width == 1280


def test_html_requests_edit_hides_browser_only_fields(client, live_server, measure_memory_usage, datastore_path):
    """html_requests has no screenshot capability, so the edit form must not render the
    viewport / language / timezone / screenshot fields (capability-gated server-side)."""
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_requests"))
    assert res.status_code == 200
    assert b'name="viewport_width"' not in res.data
    assert b'name="timezone_id"' not in res.data
    assert b'name="screenshot_format"' not in res.data

    # A browser-capable engine (html_webdriver) DOES render them
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_webdriver"))
    assert b'name="viewport_width"' in res.data
    assert b'name="timezone_id"' in res.data

    # ...but the plain client DOES render its HTTP options (timeout + user-agent)
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_requests"))
    assert b'name="timeout"' in res.data
    assert b'name="user_agent"' in res.data
    assert b'name="viewport_width"' not in res.data


def test_plain_requests_engine_is_selectable_default_in_overview(client, live_server, measure_memory_usage, datastore_path):
    """The plain HTTP client (html_requests) - and any non-browser fetcher a plugin registers -
    must ALWAYS appear in /settings/browsers so it can be set as the global default (it's the most common
    one), and it supports variations (HTTP timeout + user-agent) so Add-variation/Edit show too."""
    datastore = client.application.config.get('DATASTORE')

    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert res.status_code == 200
    # Present as a row with a default radio
    assert b'value="html_requests"' in res.data
    assert b'class="browser-default-radio"' in res.data
    # It's configurable (HTTP options) so Add-variation + Edit ARE offered
    assert url_for("ui.browser_config.browser_config_add", base_fetcher="html_requests").encode() in res.data
    assert url_for("ui.browser_config.browser_config_edit", config_id="html_requests").encode() in res.data

    # It can be made the default from here
    res = client.post(url_for("ui.browser_config.browser_config_set_default", config_id="html_requests"),
                      follow_redirects=True)
    assert b"Default browser set" in res.data
    assert datastore.data['settings']['application']['fetch_backend'] == 'html_requests'


def test_html_requests_variation_timeout_and_user_agent(client, live_server, measure_memory_usage, datastore_path):
    """A variation on the plain client stores + resolves HTTP timeout + user-agent, and the
    requests fetcher honours them (overriding the caller's timeout/UA)."""
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')

    # Create a plain-client variation with a custom timeout + user-agent via the real Add flow
    res = _add_browser(client, label="Slow bot", base_fetcher="html_requests",
                       timeout=77, user_agent="MyCrawler/1.0")
    assert b"Slow bot" in res.data
    cid = list(datastore.browser_config_store.all())[0]
    cfg = datastore.browser_config_store.get(cid)['browser_config']
    assert cfg['timeout'] == 77
    assert cfg['user_agent'] == "MyCrawler/1.0"

    # A watch using it resolves to html_requests + that FetcherConfig
    uuid = datastore.add_watch(url="https://example.com")
    datastore.data['watching'][uuid]['fetch_backend'] = cid
    _cls, backend_name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert backend_name == 'html_requests'
    assert browser_config.timeout == 77
    assert browser_config.user_agent == "MyCrawler/1.0"

    # The shared abstractions: timeout override (requests-only) + universal UA application
    # (replacing the User-Agent case-insensitively).
    assert browser_config.effective_timeout(5) == 77
    headers = browser_config.apply_user_agent({'user-agent': 'default-ua'})
    assert headers.get('User-Agent') == "MyCrawler/1.0"
    assert 'user-agent' not in headers  # old-cased key removed, not duplicated


def test_playwright_builtin_is_base_only(client, live_server, measure_memory_usage, datastore_path):
    """html_playwright_builtin isn't usable directly (ready_to_use=False) - it must not appear as
    a directly-selectable built-in browser, but it IS offered as a base engine in Add Browser,
    and a config built on it can pick a browser_type."""
    from changedetectionio.model.browser_config import list_builtin_browsers
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')

    # Not a directly-usable built-in (excluded from the watch picker list)
    assert 'html_playwright_builtin' not in [b['id'] for b in list_builtin_browsers()]

    res = client.get(url_for("ui.browser_config.browsers_overview"))
    # The overview offers "Add variation" for it (it's an available base) ...
    assert url_for("ui.browser_config.browser_config_add", base_fetcher="html_playwright_builtin").encode() in res.data
    # ... but NOT a direct Edit link (base-only, not usable as-is)
    assert url_for("ui.browser_config.browser_config_edit", config_id="html_playwright_builtin").encode() not in res.data

    # Add a variation on it choosing firefox, via the real add flow
    _add_browser(client, label="Local Firefox", base_fetcher="html_playwright_builtin", browser_type="firefox")
    cid = list(datastore.browser_config_store.all())[0]

    uuid = datastore.add_watch(url="https://example.com")
    datastore.data['watching'][uuid]['fetch_backend'] = cid
    cls, backend_name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert backend_name == 'html_playwright_builtin'
    assert browser_config.browser_type == 'firefox'
    assert cls().local_launch is True


def test_missing_browser_config_raises(client, live_server, measure_memory_usage, datastore_path):
    import pytest
    from changedetectionio.content_fetchers import resolve_content_fetcher
    from changedetectionio.model.browser_config import BrowserConfigDoesntExist
    datastore = client.application.config.get('DATASTORE')

    # Watch points at a browser config id that doesn't exist
    uuid = datastore.add_watch(url="https://example.com")
    datastore.data['watching'][uuid]['fetch_backend'] = 'deleted-config-id-1234'

    with pytest.raises(BrowserConfigDoesntExist):
        resolve_content_fetcher(datastore.data['watching'][uuid], datastore)

    # Legacy raw engine names and 'system' must NOT raise
    for legacy in ('system', 'html_requests', 'html_webdriver'):
        datastore.data['watching'][uuid]['fetch_backend'] = legacy
        resolve_content_fetcher(datastore.data['watching'][uuid], datastore)


def test_global_default_browser_resolves_for_system_watches(client, live_server, measure_memory_usage, datastore_path):
    from changedetectionio.content_fetchers import resolve_content_fetcher
    from changedetectionio.pluggy_interface import get_fetcher_capabilities
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="System Mobile", viewport_width=360, locale="es-ES")
    cid = list(datastore.browser_config_store.all())[0]

    # Make it the global default (the single source of truth 'system' resolves to)
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)
    assert datastore.data['settings']['application']['fetch_backend'] == cid

    # A watch left on 'system' resolves through the global default -> engine + its config
    uuid = datastore.add_watch(url="https://example.com")
    datastore.data['watching'][uuid]['fetch_backend'] = 'system'
    _cls, backend_name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert backend_name == 'html_webdriver'
    assert browser_config.locale == 'es-ES'
    assert browser_config.viewport_width == 360

    # Capability lookups resolve through it too (edit-page gating)
    caps = get_fetcher_capabilities(datastore.data['watching'][uuid], datastore)
    assert caps['supports_screenshots'] is True


def test_bulk_set_browser_operation(client, live_server, measure_memory_usage, datastore_path):
    """The watchlist bulk 'Set browser' modal lists the same browsers and its apply op accepts
    a saved browser-config id (not just raw engine names)."""
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, label="Bulk Mobile", viewport_width=390)
    cid = list(datastore.browser_config_store.all())[0]

    # The modal option list (rendered on the overview) includes Default, a built-in and our browser
    res = client.get(url_for("watchlist.index"))
    assert b"Default (system settings)" in res.data
    assert b'value="html_webdriver"' in res.data
    assert b"Bulk Mobile" in res.data

    uuid = datastore.add_watch(url="https://example.com")
    res = client.post(url_for("ui.form_watch_list_checkbox_operations"),
                      data={'op': 'set-fetch-backend', 'op_extradata': cid, 'uuids': uuid},
                      follow_redirects=True)
    assert datastore.data['watching'][uuid]['fetch_backend'] == cid


def test_group_browser_config_override(client, live_server, measure_memory_usage, datastore_path):
    """End-to-end through the tag edit form: the group's browser-config dropdown must list the
    available browsers (built-ins + user), saving the override must persist, and a member watch
    must then show + resolve the override."""
    from changedetectionio.content_fetchers import resolve_content_fetcher
    from changedetectionio.model.browser_config import resolve_browser_config_override
    datastore = client.application.config.get('DATASTORE')

    # A local Playwright/Firefox browser variation, so we also exercise the sub-engine icon/title
    _add_browser(client, label="Group Mobile", base_fetcher="html_playwright_builtin",
                 browser_type="firefox", viewport_width=375, locale="fr-FR")
    cid = list(datastore.browser_config_store.all())[0]

    tag_uuid = datastore.add_tag("French mobile")

    # 1) The group edit page lists the browsers to choose from (built-in + our user browser).
    #    This is what was broken - the dropdown only had "None".
    res = client.get(url_for("tags.form_tag_edit", uuid=tag_uuid))
    assert res.status_code == 200
    assert b"Group Mobile" in res.data                 # user browser listed
    assert b'value="html_webdriver"' in res.data       # built-in listed

    # 2) Save the override via the form (enabler on + pick our browser)
    client.post(url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
                data={'title': 'French mobile', 'browser_config_overrides_watch': 'y',
                      'browser_config': cid},
                follow_redirects=True)
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    assert tag.get('browser_config_overrides_watch') is True
    assert tag.get('browser_config') == cid

    # 3) A member watch: resolver reports the override, edit page shows it, fetch resolves it
    uuid = datastore.add_watch(url="https://example.com", tag_uuids=[tag_uuid])
    override = resolve_browser_config_override(datastore.data['watching'][uuid], datastore)
    assert override and override['config_id'] == cid and override['label'] == 'Group Mobile'

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    # The override message + link to the group are shown...
    assert b"fetch-backend-group-override" in res.data
    assert b"Using browser config" in res.data
    assert b"Group Mobile" in res.data
    assert url_for("tags.form_tag_edit", uuid=tag_uuid).encode() in res.data
    # ...and the normal Browser picker is NOT offered (its help text is gone -> radio replaced)
    assert b"method (default) where" not in res.data

    _cls, backend_name, _url, browser_config = resolve_content_fetcher(datastore.data['watching'][uuid], datastore)
    assert browser_config.locale == 'fr-FR'
    assert browser_config.viewport_width == 375

    # Capabilities (used to gate the Visual Selector tab) must reflect the OVERRIDING browser's
    # engine (playwright_builtin here), not the watch's own fetch_backend.
    from changedetectionio.pluggy_interface import get_fetcher_capabilities
    caps = get_fetcher_capabilities(datastore.data['watching'][uuid], datastore)
    assert caps['supports_screenshots'] is True
    assert caps['supports_xpath_element_data'] is True

    # Effective engine (for the watchlist status icon) resolves through the override.
    from changedetectionio.model.browser_config import resolve_watch_fetcher_engine
    assert resolve_watch_fetcher_engine(datastore.data['watching'][uuid], datastore) == 'html_playwright_builtin'

    # The watchlist overview status icon shows the overriding browser's name, sub-engine and group
    res = client.get(url_for("watchlist.index"))
    assert res.status_code == 200
    assert b"Group Mobile" in res.data       # config name (not a hardcoded 'Chrome')
    assert b"firefox" in res.data            # resolved sub-engine
    assert b"French mobile" in res.data      # from group ...


def test_settings_default_browser_is_readonly_and_browsers_tab_owns_it(client, live_server, measure_memory_usage, datastore_path):
    """All browser choice moved to /settings/browsers. The Settings->Fetching page shows the global
    Default browser read-only (no editable radio) and a settings save must NOT clobber it."""
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="Settings Default", viewport_width=800)
    cid = list(datastore.browser_config_store.all())[0]
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)
    assert datastore.data['settings']['application']['fetch_backend'] == cid

    # Settings page shows the read-only summary (label + link to /settings/browsers) and NO editable radio.
    res = client.get(url_for("settings.settings_page"))
    assert b"Default browser" in res.data
    assert b"Settings Default" in res.data
    assert url_for("ui.browser_config.browsers_overview").encode() in res.data
    assert b'name="application-fetch_backend"' not in res.data

    # A settings save (the form no longer carries fetch_backend) leaves the default untouched.
    res = client.post(url_for("settings.settings_page"),
                      data={"requests-time_between_check-minutes": 180,
                            "application-empty_pages_are_a_change": ""},
                      follow_redirects=True)
    assert b"Settings updated." in res.data
    assert datastore.data['settings']['application']['fetch_backend'] == cid


def test_browsers_overview_default_radio(client, live_server, measure_memory_usage, datastore_path):
    """Each usable browser row exposes a radio to set it as default; the current default is checked."""
    import re
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, label="Radio Mobile", viewport_width=390)
    cid = list(datastore.browser_config_store.all())[0]
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)

    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert b'class="browser-default-radio"' in res.data
    # Built-in engines each have a radio too (usable ones)
    assert b'value="html_webdriver"' in res.data
    # The checked radio is our default config id
    checked = re.findall(rb'<input type="radio"[^>]*?>', res.data)
    assert any(cid.encode() in tag and b'checked' in tag for tag in checked)


def test_watch_get_fetch_backend_resolution_chain(client, live_server, measure_memory_usage, datastore_path):
    """Watch.get_fetch_backend owns the whole chain: PDF / watch / 'system'->global / group override."""
    datastore = client.application.config.get('DATASTORE')

    # Global Default browser = html_webdriver (what /settings/browsers set-default writes)
    datastore.data['settings']['application']['fetch_backend'] = 'html_webdriver'

    uuid = datastore.add_watch(url="https://example.com")
    watch = datastore.data['watching'][uuid]

    # 'system' resolves to the global default (and maps to the same engine)
    watch['fetch_backend'] = 'system'
    assert watch.get_fetch_backend == 'html_webdriver'
    assert watch.resolved_fetch_engine == 'html_webdriver'

    # A watch-level choice wins over the global default
    watch['fetch_backend'] = 'html_requests'
    assert watch.get_fetch_backend == 'html_requests'

    # PDF forces html_requests regardless of the selected browser
    watch['fetch_backend'] = 'html_webdriver'
    watch['url'] = 'https://example.com/doc.pdf'
    assert watch.get_fetch_backend == 'html_requests'
    watch['url'] = 'https://example.com'

    # A group override beats the watch's own selection
    tag_uuid = datastore.add_tag("Force webdriver")
    client.post(url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
                data={'title': 'Force webdriver', 'browser_config_overrides_watch': 'y',
                      'browser_config': 'html_webdriver'}, follow_redirects=True)
    watch['fetch_backend'] = 'html_requests'
    watch['tags'] = [tag_uuid]
    assert watch.get_fetch_backend == 'html_webdriver'


def test_update_35_normalises_default_browser(client, live_server, measure_memory_usage, datastore_path):
    """update_35 turns a blank/'system'/dangling global default into a concrete built-in engine,
    but leaves an already-valid default (engine name or saved config id) untouched."""
    datastore = client.application.config.get('DATASTORE')
    app = datastore.data['settings']['application']

    # Blank -> concrete default
    app['fetch_backend'] = ''
    datastore.update_35()
    assert app['fetch_backend'] in ('html_requests', 'html_webdriver')

    # 'system' at the global level is invalid (it IS the system default) -> normalised
    app['fetch_backend'] = 'system'
    datastore.update_35()
    assert app['fetch_backend'] != 'system'

    # A dangling browser-config id -> normalised to a concrete engine
    app['fetch_backend'] = 'deleted-id-9999'
    datastore.update_35()
    assert app['fetch_backend'] != 'deleted-id-9999'

    # A valid built-in engine is left untouched (idempotent)
    app['fetch_backend'] = 'html_webdriver'
    datastore.update_35()
    assert app['fetch_backend'] == 'html_webdriver'

    # A valid saved browser-config id is left untouched
    _add_browser(client, label="Keeper", viewport_width=800)
    cid = list(datastore.browser_config_store.all())[0]
    app['fetch_backend'] = cid
    datastore.update_35()
    assert app['fetch_backend'] == cid


def test_update_36_migrates_timeout_and_default_ua(client, live_server, measure_memory_usage, datastore_path):
    """update_36 moves settings.requests.timeout + default_ua into engine-keyed browser configs
    (html_requests: timeout + UA; html_webdriver: UA) and removes the old settings keys."""
    datastore = client.application.config.get('DATASTORE')
    req = datastore.data['settings']['requests']

    # Simulate a pre-migration install
    req['timeout'] = 33
    req['default_ua'] = {'html_requests': 'ReqUA/1', 'html_webdriver': 'ChromeUA/2'}

    datastore.update_36()

    # Old settings removed
    assert 'timeout' not in req
    assert 'default_ua' not in req

    # Migrated into engine-keyed configs
    rq = datastore.browser_config_store.get('html_requests')['browser_config']
    assert rq['timeout'] == 33
    assert rq['user_agent'] == 'ReqUA/1'
    wd = datastore.browser_config_store.get('html_webdriver')['browser_config']
    assert wd['user_agent'] == 'ChromeUA/2'

    # Idempotent - a second run with nothing to migrate is a no-op
    datastore.update_36()
    assert datastore.browser_config_store.get('html_requests')['browser_config']['timeout'] == 33


def test_group_override_with_builtin_browser(client, live_server, measure_memory_usage, datastore_path):
    """A group can also override with a built-in engine (e.g. html_webdriver), not just a user browser."""
    from changedetectionio.model.browser_config import resolve_browser_config_override
    datastore = client.application.config.get('DATASTORE')

    tag_uuid = datastore.add_tag("Force Chrome")
    client.post(url_for("tags.form_tag_edit_submit", uuid=tag_uuid),
                data={'title': 'Force Chrome', 'browser_config_overrides_watch': 'y',
                      'browser_config': 'html_webdriver'},
                follow_redirects=True)

    uuid = datastore.add_watch(url="https://example.com", tag_uuids=[tag_uuid])
    override = resolve_browser_config_override(datastore.data['watching'][uuid], datastore)
    assert override is not None and override['config_id'] == 'html_webdriver'


def test_browsers_json_corruption_is_tolerated(tmp_path):
    """browsers.json can be hand-edited / restored / corrupted, so BrowserConfigStore.all() is the
    single read-side validation gate: it never lets a malformed file take down its consumers.
    Good entries survive (normalized), bad entries are dropped, extra keys are tolerated."""
    import json
    from changedetectionio.model.browser_config import BrowserConfigStore

    def store_with(text):
        p = tmp_path / "browsers.json"
        p.write_text(text)
        return BrowserConfigStore(str(tmp_path), lock=None)

    # Syntactically broken JSON -> empty, never raises
    assert store_with("{ not valid json ,,,").all() == {}

    # Top level isn't an id->entry object (a list) -> empty, never raises
    assert store_with(json.dumps([1, 2, 3])).all() == {}

    # An entry that isn't even a dict -> dropped, never raises
    assert store_with(json.dumps({"x": "i am a string"})).all() == {}

    # An entry with a bad-typed inner field -> dropped
    assert store_with(json.dumps({
        "x": {"label": "L", "base_fetcher": "html_requests",
              "browser_config": {"viewport_width": "not-a-number"}}
    })).all() == {}

    # Unknown extra keys (top level AND inside browser_config) are tolerated for version skew
    good = store_with(json.dumps({
        "keep": {"label": "Good", "base_fetcher": "html_requests", "is_default": True,
                 "browser_config": {"timeout": 5, "future_field": "ignored"}}
    })).all()
    assert list(good) == ["keep"]
    assert good["keep"]["label"] == "Good"
    assert good["keep"]["browser_config"]["timeout"] == 5
    assert "future_field" not in good["keep"]["browser_config"]  # unknown inner key stripped

    # Mixed file: the good entry survives, only the bad one is dropped
    mixed = store_with(json.dumps({
        "good": {"label": "G", "base_fetcher": "html_requests", "browser_config": {}},
        "bad": "nope",
    })).all()
    assert list(mixed) == ["good"]


def test_locked_browser_config_flag(monkeypatch):
    """LOCKED_BROWSER_CONFIG gates the /settings/browsers editing UI. browser_config_locked() is the single
    source of truth used by BOTH the blueprint registration guard and every template that links to
    the endpoint, so verify the env->bool contract here."""
    from changedetectionio.flask_app import browser_config_locked

    monkeypatch.delenv('LOCKED_BROWSER_CONFIG', raising=False)
    assert browser_config_locked() is False  # absent -> unlocked (default)

    for truthy in ('true', '1', 'yes', 'True'):
        monkeypatch.setenv('LOCKED_BROWSER_CONFIG', truthy)
        assert browser_config_locked() is True, truthy

    for falsy in ('false', '0', 'no', ''):
        monkeypatch.setenv('LOCKED_BROWSER_CONFIG', falsy)
        assert browser_config_locked() is False, repr(falsy)


def test_browsers_page_registered_and_reachable(client, live_server, measure_memory_usage, datastore_path):
    """Sanity: the /settings/browsers page is always registered and reachable (locking only disables the
    add/edit/remove actions, it never withdraws the page - see the lock test below)."""
    endpoints = {r.endpoint for r in client.application.url_map.iter_rules()}
    assert 'ui.browser_config.browsers_overview' in endpoints
    assert client.get(url_for('ui.browser_config.browsers_overview')).status_code == 200


def test_locked_browser_config_blocks_mutations(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """LOCKED_BROWSER_CONFIG keeps /settings/browsers viewable and set-default working, but disables
    add/edit/remove - both the UI affordances AND the routes (defends against a direct POST).
    The route guards read the env per-request, so toggling it here exercises the real path."""
    datastore = client.application.config.get('DATASTORE')

    # A pre-existing user variation to attempt edit/remove on (created while unlocked)
    cid = datastore.browser_config_store.add(label="Prelocked", base_fetcher="html_requests",
                                             browser_config={'timeout': 7})

    monkeypatch.setenv('LOCKED_BROWSER_CONFIG', 'true')

    # Overview still renders and lists the browser, but offers no add/edit/remove affordances
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert res.status_code == 200
    assert b"Prelocked" in res.data
    assert url_for("ui.browser_config.browser_config_edit", config_id=cid).encode() not in res.data
    assert url_for("ui.browser_config.browser_config_remove", config_id=cid).encode() not in res.data
    assert b"Add variation" not in res.data
    # ...while the set-default control is still present
    assert url_for("ui.browser_config.browser_config_set_default", config_id=cid).encode() in res.data

    # Add is rejected server-side, nothing is created
    res = _add_browser(client, label="ShouldNotExist", base_fetcher="html_requests")
    assert b"locked" in res.data.lower()
    assert not any(e.get('label') == 'ShouldNotExist' for e in datastore.browser_config_store.all().values())

    # Edit is rejected, the entry is untouched
    res = client.post(url_for("ui.browser_config.browser_config_edit", config_id=cid),
                      data={'label': 'Renamed', 'base_fetcher': 'html_requests', 'timeout': 99,
                            'screenshot_format': 'JPEG'},
                      follow_redirects=True)
    assert b"locked" in res.data.lower()
    assert datastore.browser_config_store.get(cid)['label'] == 'Prelocked'

    # Remove is rejected, the entry survives
    res = client.post(url_for("ui.browser_config.browser_config_remove", config_id=cid), follow_redirects=True)
    assert b"locked" in res.data.lower()
    assert datastore.browser_config_store.get(cid) is not None

    # Choosing the default IS still allowed
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)
    assert datastore.data['settings']['application']['fetch_backend'] == cid

    # Clean up so the shared datastore doesn't leak this config into other tests
    monkeypatch.delenv('LOCKED_BROWSER_CONFIG', raising=False)
    datastore.browser_config_store.delete(cid)


def test_config_only_stores_fields_the_engine_honours(client, live_server, measure_memory_usage, datastore_path):
    """A browser config may only carry settings its base engine can actually honour.

    Two ways junk used to reach browsers.json: an unrendered WTForms field falling back to its
    own widget default (the plain HTTP client stored browser_type='chromium' and
    delete_created_files=False, neither of which it honours), and a crafted POST naming fields
    the form never rendered. FetcherConfig.applicable_fields() is the allowlist for both, and is
    the same set the form template renders from.
    """
    datastore = client.application.config.get('DATASTORE')

    # A variation of the plain HTTP client: no screenshots, no local launch
    res = _add_browser(client, label="Fast plain client", base_fetcher="html_requests", timeout=30)
    assert b"Fast plain client" in res.data

    cid = next(c for c, e in datastore.browser_config_store.all().items()
               if e.get('label') == "Fast plain client")
    stored = datastore.browser_config_store.get(cid)['browser_config']
    assert stored.get('timeout') == 30, "a field this engine honours is kept"
    # The store re-expands every FetcherConfig key with its default on write, so what matters is
    # that no inapplicable field carries a *value*: browser_type came back as 'chromium' (the
    # SelectField default) and delete_created_files as False (unchecked box) before the filter.
    assert stored.get('browser_type') is None
    assert stored.get('delete_created_files') is True, "must stay at the model default, not the unrendered widget's"
    for untouched in ('viewport_width', 'viewport_height', 'locale', 'timezone_id'):
        assert stored.get(untouched) is None, f"{untouched} does not apply to html_requests"
    assert not stored.get('block_resource_types')

    # Same route, but the POST names browser-only fields the form never rendered for this engine
    res = _add_browser(client, label="Crafted", base_fetcher="html_requests", timeout=30,
                       viewport_width=1920, viewport_height=1080, locale='de-DE',
                       browser_type='firefox')
    assert b"Crafted" in res.data
    cid = next(c for c, e in datastore.browser_config_store.all().items()
               if e.get('label') == "Crafted")
    stored = datastore.browser_config_store.get(cid)['browser_config']
    assert stored.get('timeout') == 30
    assert stored.get('viewport_width') is None and stored.get('browser_type') is None \
        and stored.get('locale') is None

    # And the fields a real browser DOES honour still save
    res = _add_browser(client, label="German desktop", base_fetcher="html_webdriver",
                       viewport_width=1920, viewport_height=1080, locale='de-DE')
    assert b"German desktop" in res.data
    cid = next(c for c, e in datastore.browser_config_store.all().items()
               if e.get('label') == "German desktop")
    stored = datastore.browser_config_store.get(cid)['browser_config']
    assert stored.get('viewport_width') == 1920 and stored.get('locale') == 'de-DE'


def test_user_agent_cannot_carry_control_characters(client, live_server, measure_memory_usage, datastore_path):
    """The per-profile User-Agent lands in an outbound header, so CR/LF can't be stored."""
    from pydantic import ValidationError
    from changedetectionio.model.browser_config import FetcherConfig

    with pytest.raises(ValidationError):
        FetcherConfig(user_agent="Mozilla/5.0\r\nX-Injected: 1")

    datastore = client.application.config.get('DATASTORE')
    before = len(datastore.browser_config_store.all())
    res = _add_browser(client, label="Header splitter", base_fetcher="html_webdriver",
                       user_agent="Mozilla/5.0\r\nX-Injected: 1")
    assert b"Header splitter" not in res.data or b"control characters" in res.data
    assert len(datastore.browser_config_store.all()) == before, "must not have been saved"


@pytest.fixture
def acme_browser_plugin():
    """Register a whole new browser engine the way an external pip package does.

    Goes through the public `register_content_fetcher` hook rather than
    register_builtin_fetchers(), and mirrors what get_plugin_fetchers() does at import time
    (the setattr, so getattr(content_fetchers, name) resolution works). Yields the class.
    """
    import sys
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.base import Fetcher
    from changedetectionio.pluggy_interface import hookimpl, plugin_manager

    class acme_cloud_browser(Fetcher):
        fetcher_description = "ACME Cloud Browser"
        # A full browser: everything the visual selector needs
        supports_browser_steps = True
        supports_screenshots = True
        supports_xpath_element_data = True
        supports_custom_user_agent = True
        supports_request_blocking = True
        supports_page_settings = True

        def __init__(self, proxy_override=None, custom_browser_connection_url=None, **kwargs):
            super().__init__(**kwargs)

        async def run(self, *args, **kwargs):
            raise NotImplementedError("this engine is never actually fetched with in the test")

    class AcmePlugin:
        @hookimpl
        def register_content_fetcher(self):
            return ('html_acme_cloud', acme_cloud_browser)

    plugin = AcmePlugin()
    plugin_manager.register(plugin, 'acme_test_plugin')
    setattr(sys.modules['changedetectionio.content_fetchers'], 'html_acme_cloud', acme_cloud_browser)
    content_fetchers._plugin_fetchers['html_acme_cloud'] = acme_cloud_browser
    try:
        yield acme_cloud_browser
    finally:
        plugin_manager.unregister(plugin)
        content_fetchers._plugin_fetchers.pop('html_acme_cloud', None)
        delattr(sys.modules['changedetectionio.content_fetchers'], 'html_acme_cloud')


def test_plugin_can_supply_a_whole_new_browser_base(client, live_server, measure_memory_usage,
                                                    datastore_path, acme_browser_plugin):
    """A plugin-provided engine must be a first-class browser base, with no core changes.

    Pins the whole contract in one place: discovery, the /settings/browsers base row + "Add variation",
    capability-gated fields, the watch picker, resolution to the plugin's own class with its
    FetcherConfig injected, and eligibility for the Add-Watch live preview. If the browser-config
    layer ever starts assuming built-in engines, this is what says so.
    """
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers import resolve_content_fetcher
    from changedetectionio.model.browser_config import list_builtin_browsers, list_watch_browser_choices
    from changedetectionio.blueprint.add_watch_ui import browser_config as add_watch_browsers
    datastore = client.application.config.get('DATASTORE')

    # Discoverable as an engine, and offered as a browser base + in the watch picker
    assert 'html_acme_cloud' in dict(content_fetchers.available_fetchers())
    assert 'html_acme_cloud' in {b['id'] for b in list_builtin_browsers()}
    assert 'html_acme_cloud' in {v for v, _ in list_watch_browser_choices(datastore)}

    # A base row on /settings/browsers, with a working "Add variation" link
    res = client.get(url_for('ui.browser_config.browsers_overview'))
    assert b'ACME Cloud Browser' in res.data
    assert url_for('ui.browser_config.browser_config_add',
                   base_fetcher='html_acme_cloud').encode() in res.data

    # Its declared capabilities gate the form (it does screenshots -> viewport fields render)
    res = client.get(url_for('ui.browser_config.browser_config_add', base_fetcher='html_acme_cloud'))
    assert res.status_code == 200
    assert b'viewport_width' in res.data

    # Create a variation of it through the real Add flow
    res = client.post(url_for('ui.browser_config.browser_config_add', base_fetcher='html_acme_cloud'),
                      data={'label': 'ACME German mobile', 'viewport_width': 390,
                            'viewport_height': 844, 'locale': 'de-DE', 'screenshot_format': 'JPEG'},
                      follow_redirects=True)
    assert b'ACME German mobile' in res.data
    cid = next(c for c, e in datastore.browser_config_store.all().items()
               if e.get('label') == 'ACME German mobile')
    assert datastore.browser_config_store.get(cid)['base_fetcher'] == 'html_acme_cloud'

    # A watch pinned to it resolves to the PLUGIN's class, with the variation's config injected
    uuid = datastore.add_watch(url='https://example.com', extras={'fetch_backend': cid})
    watch = datastore.data['watching'][uuid]
    assert watch.resolved_fetch_engine == 'html_acme_cloud'
    cls, engine, _custom_url, cfg = resolve_content_fetcher(watch, datastore)
    assert cls is acme_browser_plugin and engine == 'html_acme_cloud'
    assert cfg.viewport_width == 390 and cfg.locale == 'de-DE'

    # And it is eligible for the Add-Watch live preview, on its own declared capabilities
    assert add_watch_browsers.is_visual_capable(cid, datastore)
    assert cid in {v for v, _ in add_watch_browsers.list_visual_browser_choices(datastore)}


def test_update_37_migrates_extra_browsers(client, live_server, measure_memory_usage, datastore_path):
    """update_37 turns each settings.requests.extra_browsers row into an External CDP browser.

    The point of keying them by their legacy 'extra_browser_<name>' selector is that NOTHING else
    has to be rewritten, so this asserts the watch / group override / global default that already
    hold that string keep resolving - now to html_external_cdp with the endpoint on the config.
    """
    from changedetectionio.content_fetchers import resolve_content_fetcher
    datastore = client.application.config.get('DATASTORE')
    req = datastore.data['settings']['requests']

    # An existing browser whose label collides with one of the rows about to be migrated
    _add_browser(client, label="BrightData", base_fetcher="html_webdriver")

    # Simulate a pre-migration install, including the blank slots the settings FieldList kept
    # and a duplicate name (two rows could share one; the old resolver took the first match)
    req['extra_browsers'] = [
        {'browser_name': 'BrightData', 'browser_connection_url': 'wss://brd.example:9222'},
        {'browser_name': '', 'browser_connection_url': ''},
        {'browser_name': 'BrightData', 'browser_connection_url': 'wss://duplicate.example:9222'},
        {'browser_name': 'Oxylabs', 'browser_connection_url': 'wss://oxy.example:9222'},
    ]

    # Things already pointing at the legacy selectors
    watch_uuid = datastore.add_watch(url="https://example.com",
                                     extras={'fetch_backend': 'extra_browser_Oxylabs'})
    tag_uuid = datastore.add_tag("Force BrightData")
    datastore.data['settings']['application']['tags'][tag_uuid]['browser_config_overrides_watch'] = True
    datastore.data['settings']['application']['tags'][tag_uuid]['browser_config'] = 'extra_browser_BrightData'
    grouped_uuid = datastore.add_watch(url="https://example.com/grouped", tag_uuids=[tag_uuid])
    datastore.data['settings']['application']['fetch_backend'] = 'extra_browser_BrightData'

    datastore.update_37()

    # The old settings key is gone, and each row is now a browser config on the new engine
    assert 'extra_browsers' not in req
    brd = datastore.browser_config_store.get('extra_browser_BrightData')
    assert brd['base_fetcher'] == 'html_external_cdp'
    assert brd['browser_config']['connection_url'] == 'wss://brd.example:9222'
    # ...with a de-duplicated label, or the /settings/browsers form could never save it again
    assert brd['label'] == 'BrightData (2)'
    oxy = datastore.browser_config_store.get('extra_browser_Oxylabs')
    assert oxy['browser_config']['connection_url'] == 'wss://oxy.example:9222'
    # The blank row was skipped, and the duplicate name did not overwrite the first
    assert datastore.browser_config_store.get('extra_browser_') is None

    # Zero rewrite: the watch that already held the legacy selector resolves to the new engine,
    # and gets the endpoint injected as part of its browser config
    watch = datastore.data['watching'][watch_uuid]
    assert watch.get_fetch_backend == 'extra_browser_Oxylabs'
    assert watch.resolved_fetch_engine == 'html_external_cdp'
    _cls, engine, _custom_url, cfg = resolve_content_fetcher(watch, datastore)
    assert engine == 'html_external_cdp'
    assert cfg.connection_url == 'wss://oxy.example:9222'

    # Group override and the global default keep working too
    grouped = datastore.data['watching'][grouped_uuid]
    assert grouped.get_fetch_backend == 'extra_browser_BrightData'
    _cls, engine, _custom_url, cfg = resolve_content_fetcher(grouped, datastore)
    assert engine == 'html_external_cdp' and cfg.connection_url == 'wss://brd.example:9222'
    datastore.data['watching'][watch_uuid]['fetch_backend'] = 'system'
    assert datastore.data['watching'][watch_uuid].resolved_fetch_engine == 'html_external_cdp'

    # Idempotent, and a re-run must not clobber a rename the user made afterwards
    datastore.browser_config_store.update('extra_browser_Oxylabs', label='My Oxylabs')
    datastore.update_37()
    assert datastore.browser_config_store.get('extra_browser_Oxylabs')['label'] == 'My Oxylabs'


def test_external_cdp_browser_requires_an_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """An External CDP browser with nowhere to connect is refused at the form, and the engine
    itself is base-only (you configure an endpoint, you don't select the bare engine)."""
    from changedetectionio import content_fetchers
    from changedetectionio.model.browser_config import list_builtin_browsers
    datastore = client.application.config.get('DATASTORE')

    assert getattr(content_fetchers.html_external_cdp, 'ready_to_use') is False
    assert 'html_external_cdp' not in {b['id'] for b in list_builtin_browsers()}, \
        "base-only: an endpoint is required, so the bare engine is never directly selectable"

    before = len(datastore.browser_config_store.all())
    res = _add_browser(client, label="No endpoint", base_fetcher="html_external_cdp")
    assert len(datastore.browser_config_store.all()) == before, "must not save without an endpoint"

    # Wrong scheme is rejected by the model (one rule, not a form copy of it)
    res = _add_browser(client, label="Wrong scheme", base_fetcher="html_external_cdp",
                       connection_url="http://not-a-websocket:9222")
    assert len(datastore.browser_config_store.all()) == before
    assert b'ws://' in res.data

    # And a good one saves, keeping the endpoint on the config
    res = _add_browser(client, label="ACME scraping browser", base_fetcher="html_external_cdp",
                       connection_url="wss://acme.example:9222")
    assert b'ACME scraping browser' in res.data
    cid = next(c for c, e in datastore.browser_config_store.all().items()
               if e.get('label') == 'ACME scraping browser')
    assert datastore.browser_config_store.get(cid)['browser_config']['connection_url'] == 'wss://acme.example:9222'


def test_live_session_refuses_a_browser_that_cannot_do_it(client, live_server, measure_memory_usage, datastore_path):
    """Browser steps / the visual selector must use the browser the watch fetches with.

    Engines that cannot drive a live session (the plain HTTP client; Selenium, which can
    screenshot but not drive the interactive session) are refused instead of silently connecting
    to whatever PLAYWRIGHT_DRIVER_URL points at - previewing a watch with a browser it does not
    check with shows the operator something untrue.
    """
    import asyncio
    from changedetectionio.blueprint.browser_steps import acquire_browser_for_fetcher
    from changedetectionio.content_fetchers.exceptions import BrowserConnectError

    for cannot in ('html_requests', 'made_up_engine', None):
        with pytest.raises(BrowserConnectError):
            asyncio.run(acquire_browser_for_fetcher(cannot, keepalive_ms=1000))


def test_browser_steps_follow_the_browsers_capability_not_an_env_var(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """Browser Steps is offered - the tab AND the script that drives it - whenever the watch's
    browser can run steps. It used to need PLAYWRIGHT_DRIVER_URL for the script, so a browser that
    launches by itself (local Playwright, a plugin) showed the tab but it did nothing."""
    monkeypatch.delenv('PLAYWRIGHT_DRIVER_URL', raising=False)
    datastore = client.application.config.get('DATASTORE')
    test_url = url_for('test_endpoint', _external=True)

    # html_webdriver is pinned to the Playwright fetcher in this file: it can run steps
    can = datastore.add_watch(url=test_url, extras={'fetch_backend': 'html_webdriver', 'paused': True})
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=can))
    assert b'id="browsersteps-tab"' in res.data
    assert b'browser-steps.js' in res.data

    # The plain HTTP client can't: neither the tab nor the script
    cannot = datastore.add_watch(url=test_url, extras={'fetch_backend': 'html_requests', 'paused': True})
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=cannot))
    assert b'id="browsersteps-tab"' not in res.data
    assert b'browser-steps.js' not in res.data


def test_live_session_hands_the_browser_config_to_a_fetcher_that_launches_its_own(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """A fetcher that launches its own browser for a live session (get_browsersteps_browser) gets
    the watch's browser config when it asks for it, and still works when it doesn't."""
    import asyncio
    from changedetectionio import content_fetchers
    from changedetectionio.blueprint.browser_steps import acquire_browser_for_fetcher
    from changedetectionio.content_fetchers.base import Fetcher
    from changedetectionio.model.browser_config import FetcherConfig
    seen = {}

    class takes_config(Fetcher):
        supports_browser_steps = True

        @classmethod
        async def get_browsersteps_browser(cls, proxy=None, keepalive_ms=None, browser_config=None):
            seen['new'] = (proxy, keepalive_ms, browser_config)
            return ('browser', None)

    class older_plugin(Fetcher):
        supports_browser_steps = True

        @classmethod
        async def get_browsersteps_browser(cls, proxy=None, keepalive_ms=None):
            seen['old'] = (proxy, keepalive_ms)
            return ('browser', None)

    monkeypatch.setattr(content_fetchers, 'html_takes_config', takes_config, raising=False)
    monkeypatch.setattr(content_fetchers, 'html_older_plugin', older_plugin, raising=False)
    config = FetcherConfig(locale='de-DE')
    proxy = {'server': 'http://proxy.example:3128'}

    assert asyncio.run(acquire_browser_for_fetcher('html_takes_config', proxy=proxy, keepalive_ms=5000, browser_config=config)) == ('browser', None)
    assert seen['new'] == (proxy, 5000, config)
    assert asyncio.run(acquire_browser_for_fetcher('html_older_plugin', proxy=proxy, keepalive_ms=5000, browser_config=config)) == ('browser', None)
    assert seen['old'] == (proxy, 5000)


def test_external_cdp_live_session_uses_its_own_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """A live session for an External CDP browser connects to THAT browser, not the system one."""
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.exceptions import BrowserConnectError
    from changedetectionio.model.browser_config import FetcherConfig

    engine = content_fetchers.html_external_cdp
    assert engine.browser_steps_connection_url(
        FetcherConfig(connection_url='wss://acme.example:9222')) == 'wss://acme.example:9222'

    # ...and says so plainly when the browser has no endpoint yet
    with pytest.raises(BrowserConnectError):
        engine.browser_steps_connection_url(FetcherConfig())


def test_update_37_survives_an_unusable_legacy_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """A legacy endpoint the model rejects must not take startup down with it.

    settings.json could be hand-edited or restored from anywhere, so one bad row logs and is
    skipped - the rest migrate, the old settings key still goes, and the app boots.
    """
    datastore = client.application.config.get('DATASTORE')
    req = datastore.data['settings']['requests']
    req['extra_browsers'] = [
        {'browser_name': 'Broken', 'browser_connection_url': 'http://not-a-websocket:9222'},
        {'browser_name': 'Good', 'browser_connection_url': 'wss://good.example:9222'},
    ]

    datastore.update_37()

    assert 'extra_browsers' not in req
    assert datastore.browser_config_store.get('extra_browser_Broken') is None
    assert datastore.browser_config_store.get('extra_browser_Good')['browser_config']['connection_url'] \
        == 'wss://good.example:9222'


def test_browser_picker_lists_each_browser_once(client, live_server, measure_memory_usage, datastore_path):
    """A saved config that shares a built-in engine's id must not appear twice in the picker.

    update_36 migrates the old per-engine request timeout / User-Agent into configs keyed
    'html_requests' / 'html_webdriver', so on any upgraded install those ids exist in BOTH the
    built-in engine list and browsers.json - which rendered the same browser as two radios on the
    watch edit page (and in the group override select).
    """
    from changedetectionio.model.browser_config import list_watch_browser_choices
    datastore = client.application.config.get('DATASTORE')

    # Exactly what an upgraded install looks like after update_36
    datastore.browser_config_store.upsert('html_requests', label='Basic fast Plaintext/HTTP Client',
                                          base_fetcher='html_requests', browser_config={'timeout': 33})

    values = [value for value, _label in list_watch_browser_choices(datastore)]
    assert len(values) == len(set(values)), f"each browser must be offered once: {values}"
    assert values.count('html_requests') == 1

    # ...and the watch edit page renders one radio per browser
    uuid = datastore.add_watch(url="https://example.com")
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    assert res.status_code == 200
    assert res.data.count(b'name="fetch_backend" type="radio" value="html_requests"') == 1

    # A renamed config wins the label, since it is the same browser under a name the user chose
    datastore.browser_config_store.update('html_requests', label='Fast plain client')
    assert dict(list_watch_browser_choices(datastore))['html_requests'] == 'Fast plain client'


# --- Device emulation (#1346) ---

def test_device_emulation_context_kwargs():
    """A device sets viewport, touch and mobile layout together, at pixel density 1 by default."""
    from changedetectionio.model.browser_config import FetcherConfig
    from changedetectionio.model.browser_devices import DEVICE_PRESETS

    pixel = DEVICE_PRESETS['Pixel 7']
    kwargs = FetcherConfig(device='Pixel 7').browser_context_kwargs()
    assert kwargs['viewport'] == pixel['viewport']
    assert kwargs['is_mobile'] is True and kwargs['has_touch'] is True
    assert kwargs['device_scale_factor'] == 1, "the descriptor's factor of 2.625 must not apply by default"

    # The device's screen size wins over a leftover viewport
    kwargs = FetcherConfig(device='Pixel 7', viewport_width=768, viewport_height=1024,
                           device_scale_factor=2).browser_context_kwargs()
    assert kwargs['viewport'] == pixel['viewport']
    assert kwargs['device_scale_factor'] == 2

    # Desktop profiles get none of the mobile options, so their behaviour is unchanged
    kwargs = FetcherConfig(viewport_width=1920, viewport_height=1080).browser_context_kwargs()
    assert kwargs == {'viewport': {'width': 1920, 'height': 1080}}
    assert FetcherConfig().browser_context_kwargs() == {}

    # pyppeteer's setViewport() dialect
    assert FetcherConfig(device='Pixel 7').puppeteer_viewport() == {
        **pixel['viewport'], 'deviceScaleFactor': 1, 'isMobile': True, 'hasTouch': True}
    assert FetcherConfig().puppeteer_viewport() is None


def test_device_user_agent_precedence():
    """Device User-Agent < the profile's own user_agent < a per-watch User-Agent header."""
    from requests.structures import CaseInsensitiveDict
    from changedetectionio.model.browser_config import FetcherConfig
    from changedetectionio.model.browser_devices import DEVICE_PRESETS

    headers = FetcherConfig(device='iPhone 15 Pro').apply_user_agent(CaseInsensitiveDict())
    assert headers['User-Agent'] == DEVICE_PRESETS['iPhone 15 Pro']['user_agent']

    headers = FetcherConfig(device='iPhone 15 Pro', user_agent='MyAgent/1.0').apply_user_agent(CaseInsensitiveDict())
    assert headers['User-Agent'] == 'MyAgent/1.0'

    # call_browser() applies the profile first and then the watch's headers on top
    headers = FetcherConfig(device='iPhone 15 Pro').apply_user_agent(CaseInsensitiveDict())
    headers.update({'user-agent': 'WatchAgent/2.0'})
    assert headers['User-Agent'] == 'WatchAgent/2.0'


def test_device_is_tolerant_on_load_and_strict_on_submit():
    """Loading browsers.json must never drop a profile over a device (that orphans its watches),
    but a submitted profile with a bad device is refused."""
    from pydantic import ValidationError
    from changedetectionio.model.browser_config import FetcherConfig

    # Loading: fall back to desktop
    assert FetcherConfig(device='Nokia 3310').device is None
    assert FetcherConfig(device='Pixel 7', browser_type='firefox').device is None

    caps = {'supports_device_emulation': True, 'supports_browser_type': True, 'supports_screenshots': True}
    with pytest.raises(ValidationError):
        FetcherConfig.from_submitted({'device': 'Nokia 3310'}, caps)
    with pytest.raises(ValidationError, match="Firefox can't emulate"):
        FetcherConfig.from_submitted({'device': 'Pixel 7', 'browser_type': 'firefox'}, caps)
    with pytest.raises(ValidationError):
        FetcherConfig.from_submitted({'device': 'Pixel 7', 'device_scale_factor': 5}, caps)
    # WebKit and Chromium can emulate phones
    assert FetcherConfig.from_submitted({'device': 'Pixel 7', 'browser_type': 'webkit'}, caps).device == 'Pixel 7'


def test_device_field_only_for_engines_that_emulate(client, live_server, measure_memory_usage, datastore_path):
    # html_playwright_builtin rather than html_webdriver, which is Selenium when no Playwright
    # driver is configured (Selenium doesn't emulate devices)
    res = client.get(url_for("ui.browser_config.browser_config_add", base_fetcher="html_playwright_builtin"))
    assert b'name="device"' in res.data
    assert b'Screen &amp; device' in res.data
    # Grouped, with desktop/custom size first
    assert b'<optgroup label="Phones">' in res.data and b'<optgroup label="Tablets">' in res.data
    assert b'Desktop (default size)' in res.data
    assert res.data.index(b'Desktop (default size)') < res.data.index(b'Pixel 7') < res.data.index(b'iPad Pro 11')

    # The plain HTTP client renders no pages, there is nothing to emulate
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_requests"))
    assert b'name="device"' not in res.data


def test_device_profile_saved_through_the_form(client, live_server, measure_memory_usage, datastore_path):
    datastore = client.application.config.get('DATASTORE')

    # A leftover viewport is cleared when a device is picked
    res = _add_browser(client, label="Phone", base_fetcher="html_playwright_builtin", browser_type='chromium',
                       device='Pixel 7', viewport_width=768, viewport_height=1024)
    assert b"Phone" in res.data
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == "Phone")
    stored = datastore.browser_config_store.get(cid)['browser_config']
    assert stored.get('device') == 'Pixel 7'
    assert stored.get('viewport_width') is None and stored.get('viewport_height') is None

    # The edit page shows it selected
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id=cid))
    assert b'<option selected value="Pixel 7">' in res.data

    # A device that doesn't exist, or Firefox emulating a phone, is refused by the form
    before = len(datastore.browser_config_store.all())
    _add_browser(client, label="Bogus device", base_fetcher="html_playwright_builtin", browser_type='chromium',
                 device='Nokia 3310')
    res = _add_browser(client, label="Firefox phone", base_fetcher="html_playwright_builtin", browser_type='firefox',
                       device='Pixel 7')
    assert b"Firefox can" in res.data
    assert len(datastore.browser_config_store.all()) == before


def test_live_browser_steps_session_uses_device_and_user_agent():
    """The Browser Steps / preview session must emulate the same device as a real check,
    including the device's User-Agent, while a per-watch User-Agent still wins."""
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    from changedetectionio.browser_steps.browser_steps import browsersteps_live_ui
    from changedetectionio.model.browser_config import FetcherConfig
    from changedetectionio.model.browser_devices import DEVICE_PRESETS

    def connect(headers):
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        ui = browsersteps_live_ui(playwright_browser=browser, headers=headers,
                                  browser_config=FetcherConfig(device='iPhone 15 Pro'))
        asyncio.run(ui.connect())
        return browser.new_context.call_args.kwargs

    kwargs = connect(headers={})
    assert kwargs['user_agent'] == DEVICE_PRESETS['iPhone 15 Pro']['user_agent']
    assert kwargs['is_mobile'] is True and kwargs['viewport'] == DEVICE_PRESETS['iPhone 15 Pro']['viewport']

    kwargs = connect(headers={'User-Agent': 'WatchAgent/2.0'})
    assert kwargs['user_agent'] == 'WatchAgent/2.0'


@pytest.mark.skipif(not os.getenv('ENABLE_DEBUG_CONTENT_FETCHER'),
                    reason="Needs ENABLE_DEBUG_CONTENT_FETCHER (set in the test-browser-config CI step)")
def test_device_reaches_the_fetcher(client, live_server, measure_memory_usage, datastore_path):
    """End-to-end through a real check: the device's context options and User-Agent arrive at
    the fetcher (the debug fetcher echoes them into the snapshot)."""
    from changedetectionio.model.browser_devices import DEVICE_PRESETS
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="Debug phone", base_fetcher="html_debug_test_browser", device='Pixel 7')
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == "Debug phone")

    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': cid})
    # Read the snapshot itself, the preview page HTML-escapes the JSON
    snapshot = _wait_for_debug_snapshot(client, datastore, uuid)
    assert '"is_mobile": true' in snapshot
    assert '"has_touch": true' in snapshot
    assert '"device_scale_factor": 1' in snapshot
    assert DEVICE_PRESETS['Pixel 7']['user_agent'] in snapshot


def test_capability_chips_are_readable(client, live_server, measure_memory_usage, datastore_path):
    """The capabilities column shows the labelled, user-facing flags (FetcherCapabilities.labels()),
    not every internal flag with its attribute name."""
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    assert b'browser-chip--cap-screenshots' in res.data
    assert b'Screenshots</span>' in res.data
    assert b'xpath element data' not in res.data
    # Every fetcher has these two, but they only decide which settings the form offers
    assert b'browser-chip--cap-custom_user_agent' not in res.data
    assert b'browser-chip--cap-cookies' not in res.data

    # model_dump() still carries every flag as a plain bool, labelled or not (plugin API, templates)
    dumped = FetcherCapabilities(supports_screenshots=True).model_dump()
    assert dumped['supports_screenshots'] is True and dumped['supports_cookies'] is False
    assert [c['flag'] for c in FetcherCapabilities(supports_screenshots=True, supports_cookies=True).chips()] == ['supports_screenshots']


def test_needs_setup_chip_goes_once_there_is_a_variation(client, live_server, measure_memory_usage, datastore_path):
    """A browser that only works through a variation (here the external one, which needs an
    endpoint) says "needs setup" - until it has a variation, then it is set up."""
    import re
    overview_url = url_for("ui.browser_config.browsers_overview")

    def _external_browser_row():
        # Just that browser's own card - others on the page may still need setting up
        html = client.get(overview_url).data.decode()
        return re.search(r'<section id="html_external_cdp" class="browser-card .*?</section>', html, re.S).group(0)

    assert 'browser-chip--needs-setup' in _external_browser_row()
    assert 'browser-card browser-engine-html_external_cdp needs-setup' in _external_browser_row()

    _add_browser(client, label="My remote browser", base_fetcher="html_external_cdp",
                 connection_url="ws://my-browser:3000")
    assert b'My remote browser' in client.get(overview_url).data
    assert 'browser-chip--needs-setup' not in _external_browser_row()


def test_browser_icon_follows_the_variations_browser(client, live_server, measure_memory_usage, datastore_path, monkeypatch):
    """The fetcher resolves the icon from the browser config (Fetcher.get_status_icon_data): a
    Playwright variation set to Firefox shows Firefox - next to it on /settings/browsers and on its
    watches in the watch list - while the Playwright browser itself keeps the Playwright icon."""
    import re
    from changedetectionio import content_fetchers
    from changedetectionio.content_fetchers.playwright_builtin import fetcher as local_playwright
    from changedetectionio.model.browser_config import FetcherConfig, browser_icon_data
    datastore = client.application.config.get('DATASTORE')
    # The local Playwright browser is only offered where the playwright library is installed;
    # nothing is fetched here, so offer it regardless and the test runs everywhere
    monkeypatch.setitem(content_fetchers._plugin_fetchers, 'html_playwright_builtin', local_playwright)
    monkeypatch.setattr(content_fetchers, 'html_playwright_builtin', local_playwright, raising=False)

    # The resolver itself: the fetcher alone, then each browser it can launch
    assert browser_icon_data('html_playwright_builtin')['filename'] == 'playwright-icon.png'
    for browser_type, icon in (('chromium', 'google-chrome-icon.png'), ('firefox', 'firefox-icon.svg'), ('webkit', 'webkit-icon.svg')):
        assert browser_icon_data('html_playwright_builtin', FetcherConfig(browser_type=browser_type))['filename'] == icon
        assert browser_icon_data('html_playwright_builtin', {'browser_type': browser_type})['filename'] == icon
        assert client.get(url_for('static_content', group='images', filename=icon)).status_code == 200
    # A fetcher with one kind of browser answers the same whatever the config; the plain client has none
    assert browser_icon_data('html_webdriver', FetcherConfig(browser_type='firefox'))['filename'] == 'google-chrome-icon.png'
    assert browser_icon_data('html_requests') is None

    # The form offers each browser as a tile carrying that same icon, the default one chosen
    form_html = client.get(url_for("ui.browser_config.browser_config_add", base_fetcher='html_playwright_builtin')).data.decode()
    tiles = re.findall(r'<label class="browser-type-option">.*?</label>', form_html, re.S)
    assert len(tiles) == 3
    for tile, (browser_type, icon) in zip(tiles, (('chromium', 'google-chrome-icon.png'), ('firefox', 'firefox-icon.svg'), ('webkit', 'webkit-icon.svg'))):
        assert f'type="radio" value="{browser_type}"' in tile and icon in tile
        assert ('checked' in tile) == (browser_type == 'chromium')

    _add_browser(client, label="German desktop", base_fetcher="html_playwright_builtin", browser_type='firefox', locale='de-DE')
    _add_browser(client, label="Safari-like", base_fetcher="html_playwright_builtin", browser_type='webkit')
    ids = {e['label']: cid for cid, e in datastore.browser_config_store.all().items()}

    # /settings/browsers: Playwright's own icon on its card, each variation's browser on its row
    html = client.get(url_for("ui.browser_config.browsers_overview")).data.decode()
    card = re.search(r'<section id="html_playwright_builtin" class="browser-card .*?</section>', html, re.S).group(0)
    head, variations = card.split('<ul class="browser-variations">')
    assert 'playwright-icon.png' in head and 'firefox-icon.svg' not in head
    assert 'playwright-icon.png' not in variations
    rows = re.split(r'<li id="[^"]*" class="browser-variation-row', variations)[1:]
    assert len(rows) == 2
    german_row = next(r for r in rows if 'German desktop' in r)
    assert 'firefox-icon.svg' in german_row and 'webkit-icon.svg' not in german_row
    assert 'webkit-icon.svg' in next(r for r in rows if 'Safari-like' in r)
    # ...and what the variation changes, in words: the language by name with its flag
    assert '<span class="browser-chip browser-chip--locale" title="de-DE">' in german_row
    assert 'fi fi-de' in german_row

    # The watch list: a watch shows the browser its variation runs
    test_url = url_for('test_endpoint', _external=True)
    firefox_watch = datastore.add_watch(url=test_url, extras={'fetch_backend': ids['German desktop']})
    webkit_watch = datastore.add_watch(url=test_url, extras={'fetch_backend': ids['Safari-like']})
    plain_watch = datastore.add_watch(url=test_url, extras={'fetch_backend': 'html_requests'})
    html = client.get(url_for("watchlist.index")).data.decode()

    def _row(uuid):
        return re.search(rf'<tr id="{uuid}".*?</tr>', html, re.S).group(0)

    assert 'firefox-icon.svg' in _row(firefox_watch)
    assert 'playwright-icon.png' not in _row(firefox_watch)
    assert 'title="German desktop (firefox)"' in _row(firefox_watch)
    assert 'webkit-icon.svg' in _row(webkit_watch)
    for icon in ('firefox-icon.svg', 'webkit-icon.svg', 'playwright-icon.png', 'google-chrome-icon.png'):
        assert icon not in _row(plain_watch)

    # The Browser picker on a watch's edit page: every choice carries its browser's icon, and
    # "Default" the icon of whatever the default browser currently is
    def _picker_choices():
        html = client.get(url_for("ui.ui_edit.edit_page", uuid=plain_watch)).data.decode()
        picker = re.search(r'<ul id="fetch_backend".*?</ul>', html, re.S).group(0)
        return {re.search(r'value="([^"]+)"', li).group(1): li for li in picker.split('<li>')[1:]}

    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    choices = _picker_choices()
    assert 'firefox-icon.svg' in choices[ids['German desktop']]
    assert 'webkit-icon.svg' in choices[ids['Safari-like']]
    assert 'google-chrome-icon.png' in choices['html_webdriver']
    # The plain client has no icon of its own, so a neutral one - and so does a default set to it
    for plain in ('html_requests', 'system'):
        assert 'data-feather="zap"' in choices[plain] and 'status-icon' not in choices[plain]
    datastore.data['settings']['application']['fetch_backend'] = ids['German desktop']
    assert 'firefox-icon.svg' in _picker_choices()['system']
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'

    # A group override changes the browser, so it changes the icon
    tag_uuid = datastore.add_tag(title="Firefoxers")
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    tag['browser_config'] = ids['German desktop']
    tag['browser_config_overrides_watch'] = True
    datastore.data['watching'][plain_watch]['tags'] = [tag_uuid]
    html = client.get(url_for("watchlist.index")).data.decode()
    assert 'firefox-icon.svg' in _row(plain_watch)

    # The group's own picker is the same list of radio buttons with icons - minus "Default",
    # its checkbox is the off switch - with the group's browser chosen
    html = client.get(url_for("tags.form_tag_edit", uuid=tag_uuid)).data.decode()
    picker = re.search(r'<ul id="browser_config".*?</ul>', html, re.S).group(0)
    choices = {re.search(r'value="([^"]+)"', li).group(1): li for li in picker.split('<li>')[1:]}
    assert 'system' not in choices
    assert 'type="radio"' in choices[ids['German desktop']] and 'firefox-icon.svg' in choices[ids['German desktop']]
    assert 'webkit-icon.svg' in choices[ids['Safari-like']]
    assert [value for value, li in choices.items() if 'checked' in li] == [ids['German desktop']]
    assert '<select' not in picker


def test_browsers_table_has_css_hooks(client, live_server, measure_memory_usage, datastore_path):
    """Deployments hide parts of the browsers page with CSS alone, so every region, card, row
    and chip must stay addressable by class."""
    import re
    _add_browser(client, label="Phone", base_fetcher="html_playwright_builtin", browser_type='chromium',
                 device='Pixel 7', locale='de-DE')
    res = client.get(url_for("ui.browser_config.browsers_overview"))
    for column in (b'col-default', b'col-browser', b'col-capabilities', b'col-actions'):
        assert b'<div class="' + column in res.data
    assert b'browser-engine-html_requests' in res.data
    assert b'browser-engine-html_playwright_builtin' in res.data
    assert b'browser-chip--cap-screenshots' in res.data
    assert b'browser-chip--plain-text' in res.data
    # A variation's settings are chips too, each with its own class
    assert re.search(rb'browser-chip--device">.*?Pixel 7</span>', res.data, re.S)
    assert b'<span class="browser-chip browser-chip--locale" title="de-DE">' in res.data


def test_watch_browser_picker_links_user_variations(client, live_server, measure_memory_usage, datastore_path):
    """On the watch edit page a browser the user added links to its own row on the browsers page
    (/settings/browsers#its-name), where that row is the link's target; built-ins aren't linked."""
    import re
    from changedetectionio.model.browser_config import browser_anchors
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, label="My firefox", base_fetcher="html_playwright_builtin", browser_type='firefox')
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == "My firefox")
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    overview_url = url_for("ui.browser_config.browsers_overview")

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=uuid))
    # Only the browser's own name is the link, the engine name in front of it is plain text.
    # The anchor is its name as a machine name, not its uuid.
    assert f'Local Playwright: <a href="{overview_url}#my-firefox" title="Manage browsers">My firefox</a>'.encode() in res.data
    # Still a normal radio choice, same markup WTForms would produce
    assert f'type="radio" value="{cid}"'.encode() in res.data
    assert b'<ul id="fetch_backend" class="browser-choice-list fetch-backend">' in res.data
    # Built-in engines aren't linked
    assert f'{overview_url}#html_requests'.encode() not in res.data

    # That anchor is exactly one row on the browsers page - the one for this browser
    html = client.get(overview_url).data.decode()
    targets = re.findall(r'<li id="my-firefox" class="browser-variation-row[^"]*">', html)
    assert len(targets) == 1
    row = html[html.index(targets[0]):].split('</li>')[0]
    assert '<strong>My firefox</strong>' in row
    # ...and a built-in browser's card is a target by its id
    assert '<section id="html_requests" class="browser-card' in html

    # Two names that would share a machine name, and one that equals a built-in's id, still
    # each get an anchor of their own
    _add_browser(client, label="my-firefox", base_fetcher="html_playwright_builtin", browser_type='firefox')
    _add_browser(client, label="html requests", base_fetcher="html_playwright_builtin", browser_type='webkit')
    _add_browser(client, label="html_requests", base_fetcher="html_playwright_builtin", browser_type='webkit')
    anchors = browser_anchors(datastore)
    assert len(anchors) == 4 and len(set(anchors.values())) == 4
    assert 'html_requests' not in anchors.values()
    html = client.get(overview_url).data.decode()
    for anchor in anchors.values():
        assert html.count(f' id="{anchor}"') == 1

def test_page_settings_only_for_engines_that_apply_them():
    """Screen size, locale and timezone need supports_page_settings, not just screenshots: an engine
    that takes screenshots but can't set those (Selenium today, or a plugin engine such as a remote
    solver) mustn't show or store them."""
    from changedetectionio.content_fetchers.base import FetcherCapabilities
    from changedetectionio.content_fetchers.playwright import fetcher as playwright_fetcher
    from changedetectionio.content_fetchers.webdriver_selenium import fetcher as selenium_fetcher
    from changedetectionio.model.browser_config import FetcherConfig

    page_fields = {'viewport_width', 'viewport_height', 'locale', 'timezone_id'}
    selenium = FetcherConfig.applicable_fields(FetcherCapabilities.from_fetcher(selenium_fetcher))
    assert FetcherCapabilities.from_fetcher(selenium_fetcher).supports_screenshots
    assert not page_fields & selenium
    assert page_fields <= FetcherConfig.applicable_fields(FetcherCapabilities.from_fetcher(playwright_fetcher))


def test_visual_selector_tab_only_when_the_browser_supports_it(client, live_server, measure_memory_usage, datastore_path):
    """The Visual Selector needs element positions, which only a real browser provides."""
    datastore = client.application.config.get('DATASTORE')
    plain = datastore.add_watch(url='https://example.com/plain', extras={'paused': True, 'fetch_backend': 'html_requests'})
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=plain))
    assert b'id="visualselector-tab"' not in res.data and b'id="visualselector"' not in res.data

    _add_browser(client, label="Full browser", base_fetcher="html_playwright_builtin", browser_type='chromium')
    cid = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == "Full browser")
    browser = datastore.add_watch(url='https://example.com/browser', extras={'paused': True, 'fetch_backend': cid})
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=browser))
    assert b'id="visualselector-tab"' in res.data


def test_visual_selector_tab_follows_group_override_and_system_default(client, live_server, measure_memory_usage, datastore_path):
    """The tab follows the browser the watch really uses: its own choice, else its group's
    override, else the system default browser."""
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, label="Full browser", base_fetcher="html_playwright_builtin", browser_type='chromium')
    full = next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == "Full browser")

    def has_tab(uuid):
        return b'id="visualselector-tab"' in client.get(url_for("ui.ui_edit.edit_page", uuid=uuid)).data

    # Watch on 'system', system default is the plain HTTP client
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    uuid = datastore.add_watch(url='https://example.com/x', extras={'paused': True, 'fetch_backend': 'system'})
    assert not has_tab(uuid)

    # System default becomes a real browser
    datastore.data['settings']['application']['fetch_backend'] = full
    assert has_tab(uuid)

    # A group overriding its watches' browser with the plain client wins over the system default
    datastore.data['settings']['application']['fetch_backend'] = full
    tag_uuid = datastore.add_tag(title='Plain group')
    tag = datastore.data['settings']['application']['tags'][tag_uuid]
    tag['browser_config_overrides_watch'] = True
    tag['browser_config'] = 'html_requests'
    datastore.data['watching'][uuid]['tags'] = [tag_uuid]
    assert not has_tab(uuid)
