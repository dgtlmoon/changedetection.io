#!/usr/bin/env python3
"""Tests for named browser configs (browsers.json) and the watch-level Browser picker."""
import os
import time
import pytest
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def _add_browser(client, label="Mobile de-DE", base_fetcher="html_webdriver", **cfg):
    # Add via the per-base "Add variation" route (base is in the URL, not the form).
    data = {'label': label, 'screenshot_format': 'JPEG'}
    data.update(cfg)
    return client.post(url_for("ui.browser_config.browser_config_add", base_fetcher=base_fetcher),
                       data=data, follow_redirects=True)


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

    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    datastore.data['watching'][uuid]['fetch_backend'] = cid

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    # The debug fetcher is instant; make sure the snapshot is committed before previewing.
    for _ in range(30):
        if datastore.data['watching'][uuid].history_n:
            break
        time.sleep(0.2)

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

    # Remove
    client.post(url_for("ui.browser_config.browser_config_remove", config_id=cid), follow_redirects=True)
    assert len(datastore.browser_config_store.all()) == 0


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
    must ALWAYS appear in /browsers so it can be set as the global default (it's the most common
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
    """All browser choice moved to /browsers. The Settings->Fetching page shows the global
    Default browser read-only (no editable radio) and a settings save must NOT clobber it."""
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, label="Settings Default", viewport_width=800)
    cid = list(datastore.browser_config_store.all())[0]
    client.post(url_for("ui.browser_config.browser_config_set_default", config_id=cid), follow_redirects=True)
    assert datastore.data['settings']['application']['fetch_backend'] == cid

    # Settings page shows the read-only summary (label + link to /browsers) and NO editable radio.
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

    # Global Default browser = html_webdriver (what /browsers set-default writes)
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


def test_update_34_normalises_default_browser(client, live_server, measure_memory_usage, datastore_path):
    """update_34 turns a blank/'system'/dangling global default into a concrete built-in engine,
    but leaves an already-valid default (engine name or saved config id) untouched."""
    datastore = client.application.config.get('DATASTORE')
    app = datastore.data['settings']['application']

    # Blank -> concrete default
    app['fetch_backend'] = ''
    datastore.update_34()
    assert app['fetch_backend'] in ('html_requests', 'html_webdriver')

    # 'system' at the global level is invalid (it IS the system default) -> normalised
    app['fetch_backend'] = 'system'
    datastore.update_34()
    assert app['fetch_backend'] != 'system'

    # A dangling browser-config id -> normalised to a concrete engine
    app['fetch_backend'] = 'deleted-id-9999'
    datastore.update_34()
    assert app['fetch_backend'] != 'deleted-id-9999'

    # A valid built-in engine is left untouched (idempotent)
    app['fetch_backend'] = 'html_webdriver'
    datastore.update_34()
    assert app['fetch_backend'] == 'html_webdriver'

    # A valid saved browser-config id is left untouched
    _add_browser(client, label="Keeper", viewport_width=800)
    cid = list(datastore.browser_config_store.all())[0]
    app['fetch_backend'] = cid
    datastore.update_34()
    assert app['fetch_backend'] == cid


def test_update_35_migrates_timeout_and_default_ua(client, live_server, measure_memory_usage, datastore_path):
    """update_35 moves settings.requests.timeout + default_ua into engine-keyed browser configs
    (html_requests: timeout + UA; html_webdriver: UA) and removes the old settings keys."""
    datastore = client.application.config.get('DATASTORE')
    req = datastore.data['settings']['requests']

    # Simulate a pre-migration install
    req['timeout'] = 33
    req['default_ua'] = {'html_requests': 'ReqUA/1', 'html_webdriver': 'ChromeUA/2'}

    datastore.update_35()

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
    datastore.update_35()
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
