#!/usr/bin/env python3
"""Tests for named browser configs (browsers.json) and the watch-level Browser picker."""
from flask import url_for
from .util import live_server_setup, wait_for_all_checks


def _add_browser(client, label="Mobile de-DE", base_fetcher="html_webdriver", **cfg):
    data = {'label': label, 'base_fetcher': base_fetcher, 'screenshot_format': 'JPEG'}
    data.update(cfg)
    return client.post(url_for("ui.browser_config.browser_config_add"), data=data, follow_redirects=True)


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

    _add_browser(client, label="Group Mobile", viewport_width=375, locale="fr-FR")
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
