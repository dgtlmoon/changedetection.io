"""
Smoke test for the LLM_FEATURES_DISABLED env var.

The env var is intended to hide every LLM/AI surface (settings tab, edit tab,
base-template AI toggle/modal) for hosted deployments. This test renders the
three primary pages with the env var set and verifies that none of the
LLM-related markers leak through.
"""
from flask import url_for


def _llm_markers_absent(body: bytes, where: str = ''):
    """All of these strings appear in LLM UI surfaces — none should render."""
    for marker in (b'AI / LLM', b'toggle-ai-mode', b'llm-not-configured-modal',
                   b'id="ai-llm"', b'#ai-llm', b'href="#ai"'):
        if marker in body:
            idx = body.find(marker)
            context = body[max(0, idx - 80):idx + len(marker) + 80].decode('utf-8', 'replace')
            raise AssertionError(f"[{where}] {marker!r} found in body, context: ...{context}...")


def test_llm_features_disabled_hides_ui(client, live_server, monkeypatch):
    monkeypatch.setenv('LLM_FEATURES_DISABLED', 'true')

    # The Add-Watch page (checked at the end) is gated on having a browser that can render a
    # live preview, which a plain test container doesn't - pretend one is installed so this
    # test stays about LLM surfaces, not about which fetchers happen to be available.
    from changedetectionio.blueprint.add_watch_ui import browser_config
    monkeypatch.setattr(browser_config, 'list_visual_browser_choices',
                        lambda datastore: [('html_webdriver', 'WebDriver Chrome/Javascript')])

    # Sanity: helper reports the env var is in effect
    from changedetectionio.llm.evaluator import is_llm_features_disabled, get_llm_config
    assert is_llm_features_disabled() is True
    # get_llm_config() must return None so every `if llm_configured` template hides
    datastore = client.application.config.get('DATASTORE')
    assert get_llm_config(datastore) is None

    # 1. Watch list (base.html + menu.html surface)
    res = client.get(url_for('watchlist.index'))
    assert res.status_code == 200
    _llm_markers_absent(res.data, where='watchlist')

    # 2. Settings page (should not have an AI / LLM tab or the LLM tab body)
    res = client.get(url_for('settings.settings_page'))
    assert res.status_code == 200
    _llm_markers_absent(res.data, where='settings')

    # 3. Edit page for a watch (should not have an AI / LLM tab or include_llm_intent body)
    uuid = datastore.add_watch(url='http://example.com', extras={'title': 'Disabled LLM watch'})
    res = client.get(url_for('ui.ui_edit.edit_page', uuid=uuid))
    assert res.status_code == 200
    _llm_markers_absent(res.data, where='edit')
    # The watch-edit-only intent textarea should also be absent
    assert b'name="llm_intent"' not in res.data
    assert b'name="llm_change_summary"' not in res.data

    # 4. Add-watch page - with no "what matters" intent box there is nothing to choose
    # between, so element selection is always on and the opt-in checkbox is not rendered.
    res = client.get(url_for('add_watch_ui.add_watch_ui_index'))
    assert res.status_code == 200
    _llm_markers_absent(res.data, where='add-watch-ui')
    assert b'name="llm_intent"' not in res.data
    assert b'id="by-element-toggle"' not in res.data
    assert b'for="by-element-toggle"' not in res.data   # no label either - it isn't a choice
    assert b'id="by-element-toggle-group"' in res.data


def test_llm_features_enabled_by_default(client, live_server, monkeypatch):
    """When LLM_FEATURES_DISABLED is unset, the AI / LLM surfaces are still rendered."""
    monkeypatch.delenv('LLM_FEATURES_DISABLED', raising=False)

    from changedetectionio.llm.evaluator import is_llm_features_disabled
    assert is_llm_features_disabled() is False

    res = client.get(url_for('settings.settings_page'))
    assert res.status_code == 200
    # The AI / LLM settings tab anchor should be present when not disabled
    assert b'href="#ai"' in res.data

    # With an LLM configured, the Add-watch page offers both ways of narrowing a watch,
    # so "Select by element" goes back to being an opt-in checkbox.
    monkeypatch.setenv('LLM_MODEL', 'gemini/gemini-2.5-flash')
    from changedetectionio.blueprint.add_watch_ui import browser_config
    monkeypatch.setattr(browser_config, 'list_visual_browser_choices',
                        lambda datastore: [('html_webdriver', 'WebDriver Chrome/Javascript')])
    res = client.get(url_for('add_watch_ui.add_watch_ui_index'))
    assert res.status_code == 200
    assert b'name="llm_intent"' in res.data
    assert b'id="by-element-toggle"' in res.data
