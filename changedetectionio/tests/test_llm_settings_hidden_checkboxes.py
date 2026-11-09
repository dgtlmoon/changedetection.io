#!/usr/bin/env python3
"""
A save of the AI / LLM settings page must not switch off checkboxes the page didn't show.

An unticked checkbox posts nothing, and WTForms reads a missing checkbox as False. Some checkboxes are shown only
once a model is saved, others only when the model doesn't come from LLM_MODEL. Seen in the wild: "Remove provider",
pick a new model, Save - and "Use LLM as a fallback for extracting price and restock info" was off.
"""

from flask import url_for


def _llm(client):
    return client.application.config.get('DATASTORE').data['settings']['application'].setdefault('llm', {})


def test_new_provider_after_remove_keeps_behaviour_checkboxes(client, live_server, measure_memory_usage, datastore_path):
    llm = _llm(client)
    llm.update({'model': 'gpt-4o-mini', 'api_key': 'sk-old', 'restock_use_fallback_extract': True,
                'override_diff_with_summary': True})

    res = client.post(url_for('settings.llm.llm_clear'), follow_redirects=True)
    assert res.status_code == 200

    # With no model saved, the page shows neither checkbox, so the next Save can't post them
    page = client.get(url_for('settings.llm.llm_settings_page')).data
    assert b'id="llm-restock_use_fallback_extract"' not in page
    assert b'id="llm-override_diff_with_summary"' not in page

    res = client.post(url_for('settings.llm.llm_settings_page'),
                      data={'llm-enabled': 'y', 'llm-model': 'claude-haiku-5-5', 'llm-api_key': 'sk-new'},
                      follow_redirects=True)
    assert res.status_code == 200

    llm = _llm(client)
    assert llm.get('model') == 'claude-haiku-5-5'
    assert llm.get('restock_use_fallback_extract') is True
    assert llm.get('override_diff_with_summary') is True


def test_unticking_a_shown_checkbox_still_switches_it_off(client, live_server, measure_memory_usage, datastore_path):
    llm = _llm(client)
    llm.update({'model': 'gpt-4o-mini', 'api_key': 'sk-kept', 'restock_use_fallback_extract': True,
                'override_diff_with_summary': True})

    page = client.get(url_for('settings.llm.llm_settings_page')).data
    assert b'id="llm-restock_use_fallback_extract"' in page

    # Unticked: the checkbox is on the page but posts nothing
    res = client.post(url_for('settings.llm.llm_settings_page'),
                      data={'llm-enabled': 'y', 'llm-model': 'gpt-4o-mini', 'llm-override_diff_with_summary': 'y'},
                      follow_redirects=True)
    assert res.status_code == 200

    llm = _llm(client)
    assert llm.get('restock_use_fallback_extract') is False
    assert llm.get('override_diff_with_summary') is True


def test_env_configured_save_keeps_hidden_checkboxes(client, live_server, measure_memory_usage, datastore_path,
                                                     monkeypatch):
    # A model saved in the UI before LLM_MODEL was set (local_thinking_off is only stored alongside a saved model)
    monkeypatch.setenv('LLM_MODEL', 'gpt-4o-mini')
    llm = _llm(client)
    llm.update({'model': 'ollama/llama3', 'debug': True, 'local_thinking_off': True})

    page = client.get(url_for('settings.llm.llm_settings_page')).data
    assert b'id="llm-debug"' not in page
    assert b'id="llm-local_thinking_off"' not in page

    res = client.post(url_for('settings.llm.llm_settings_page'), data={'llm-enabled': 'y'}, follow_redirects=True)
    assert res.status_code == 200

    llm = _llm(client)
    assert llm.get('debug') is True
    assert llm.get('local_thinking_off') is True
