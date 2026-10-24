#!/usr/bin/env python3
"""Plugins extending the whole browser lifecycle: a section on the browser edit page, its settings
stored with the browser, changing the request just before the browser runs, and a callback after.
See changedetectionio/browser_lifecycle.py."""
import asyncio
import os
import time

import pytest
from flask import url_for
from wtforms import BooleanField, Form, RadioField, StringField, validators

from changedetectionio.plugin_api import BrowserConfigSection, BrowserRequest, hookimpl
from changedetectionio.pluggy_interface import plugin_manager
from .util import wait_for_all_checks

PLUGIN_ID = 'test_lifecycle'


class _ModeForm(Form):
    mode = RadioField('Solver mode', default='off', choices=[
        ('off', 'Off'), ('always', 'Always'), ('on_403', 'Only when a page returns 403'), ('fail', 'Fail')])
    note = StringField('Note', validators=[validators.Optional(), validators.Length(max=10)])
    enabled = BooleanField('Enabled')


class LifecyclePlugin:
    """Uses every stage. Its section isn't offered for the plain HTTP client."""

    def __init__(self):
        self.altered = []
        self.finished = []

    @hookimpl
    def browser_config_form_section(self, base_fetcher, capabilities):
        if base_fetcher == 'html_requests':
            return None
        return BrowserConfigSection(plugin_id=PLUGIN_ID, label='Test lifecycle', form_class=_ModeForm,
                                    description='Settings from a test plugin')

    @hookimpl
    async def browser_request_alter(self, request):
        settings = request.plugin_settings(PLUGIN_ID)
        self.altered.append((request.purpose, request.fetcher_name, settings))
        if settings.get('mode') == 'fail':
            raise RuntimeError("The test solver is unavailable")
        if settings.get('mode') == 'always':
            request.headers['X-Test-Lifecycle'] = 'yes'
            request.cookies.append({'name': 'cf_test', 'value': 'abc'})
            request.proxy_url = 'http://plugin-proxy.example:3128'
            request.extra['token'] = 123

    @hookimpl
    def browser_request_finished(self, request, fetcher, error):
        self.finished.append({'fetcher_name': request.fetcher_name, 'token': request.extra.get('token'),
                              'error': error, 'had_fetcher': fetcher is not None})


@pytest.fixture
def lifecycle_plugin():
    plugin = LifecyclePlugin()
    plugin_manager.register(plugin, name='test_lifecycle_plugin')
    yield plugin
    plugin_manager.unregister(name='test_lifecycle_plugin')


def _add_browser(client, label, base_fetcher, **data):
    return client.post(url_for("ui.browser_config.browser_config_add", base_fetcher=base_fetcher),
                       data={'label': label, **data}, follow_redirects=True)


def _browser_id(datastore, label):
    return next(c for c, e in datastore.browser_config_store.all().items() if e.get('label') == label)


# --- Unit level ---

def test_cookies_are_scoped_to_the_requested_url():
    request = BrowserRequest(url='https://example.com/page', fetcher_name='html_requests', fetcher_class=None,
                             browser_config=None, headers={},
                             cookies=[{'name': 'a', 'value': '1'},
                                      {'name': 'b', 'value': '2', 'domain': '.example.com', 'url': 'https://x.test'},
                                      {'value': 'no name'}])
    cookies = request.cookies_for_browser()
    assert cookies[0] == {'name': 'a', 'value': '1', 'url': 'https://example.com/page'}
    assert cookies[1] == {'name': 'b', 'value': '2', 'domain': '.example.com', 'path': '/'}, "url or domain, never both"
    assert len(cookies) == 2, "a cookie without a name is dropped"
    assert request.plugin_settings('anything') == {}


def test_plugin_settings_tolerant_on_load_strict_on_submit():
    from pydantic import ValidationError
    from changedetectionio.model.browser_config import FetcherConfig

    loaded = FetcherConfig(plugin_settings={'good': {'mode': 'always'}, 'Bad Id': {}, 'notadict': 'x'})
    assert loaded.plugin_settings == {'good': {'mode': 'always'}}
    assert FetcherConfig(plugin_settings=['nonsense']).plugin_settings == {}
    assert loaded.plugin_config('good') == {'mode': 'always'}
    loaded.plugin_config('good')['mode'] = 'changed'
    assert loaded.plugin_config('good') == {'mode': 'always'}, "plugin_config() hands out a copy"

    with pytest.raises(ValidationError):
        FetcherConfig.from_submitted({'plugin_settings': {'Bad Id': {}}}, {})


def test_live_session_applies_cookies_and_reports_finished_once():
    from unittest.mock import AsyncMock, MagicMock
    from changedetectionio.browser_steps.browser_steps import browsersteps_live_ui

    finished = []

    class Plugin:
        @hookimpl
        def browser_request_finished(self, request, fetcher, error):
            finished.append((request.purpose, fetcher))

    plugin_manager.register(Plugin(), name='test_live_finished')
    try:
        page = MagicMock()
        page.wait_for_timeout = AsyncMock()
        page.request_gc = AsyncMock()
        page.close = AsyncMock()
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        context.add_cookies = AsyncMock()
        context.close = AsyncMock()
        browser = MagicMock()
        browser.new_context = AsyncMock(return_value=context)
        request = BrowserRequest(url='https://example.com', fetcher_name='html_webdriver', fetcher_class=None,
                                 browser_config=None, headers={}, purpose='browser_steps')
        ui = browsersteps_live_ui(playwright_browser=browser, cookies=[{'name': 'a', 'value': '1', 'url': 'https://example.com'}],
                                  browser_request=request)

        async def run():
            await ui.connect()
            ui.mark_as_closed()          # the page closing marks the session cleaned up first
            await ui.cleanup()
            await ui.cleanup()
        asyncio.run(run())

        context.add_cookies.assert_awaited_once_with([{'name': 'a', 'value': '1', 'url': 'https://example.com'}])
        assert finished == [('browser_steps', None)], "called once, even after the page closed itself"
    finally:
        plugin_manager.unregister(name='test_live_finished')


# --- Browser edit page ---

def test_plugin_section_on_the_browser_edit_page(client, live_server, measure_memory_usage, datastore_path, lifecycle_plugin):
    res = client.get(url_for("ui.browser_config.browser_config_add", base_fetcher="html_playwright_builtin"))
    html = res.data.decode()
    browser_pane = html.split('id="browser"')[1].split('tab-pane-inner')[0]
    assert 'Test lifecycle' in browser_pane and 'Settings from a test plugin' in browser_pane
    assert 'name="plugin_test_lifecycle-mode"' in browser_pane
    assert 'Only when a page returns 403' in browser_pane

    # The plugin chose not to offer it for the plain HTTP client
    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id="html_requests"))
    assert b'plugin_test_lifecycle' not in res.data


def test_plugin_settings_saved_reloaded_and_validated(client, live_server, measure_memory_usage, datastore_path, lifecycle_plugin):
    datastore = client.application.config.get('DATASTORE')

    _add_browser(client, "Solver", "html_playwright_builtin", browser_type='chromium',
                 **{'plugin_test_lifecycle-mode': 'on_403', 'plugin_test_lifecycle-note': 'hello'})
    cid = _browser_id(datastore, "Solver")
    stored = datastore.browser_config_store.get(cid)['browser_config']['plugin_settings']
    assert stored == {PLUGIN_ID: {'mode': 'on_403', 'note': 'hello', 'enabled': False}}

    res = client.get(url_for("ui.browser_config.browser_config_edit", config_id=cid))
    assert b'checked id="plugin_test_lifecycle-mode-2"' in res.data or \
           b'id="plugin_test_lifecycle-mode-2" name="plugin_test_lifecycle-mode" type="radio" value="on_403" checked' in res.data \
           or b'value="on_403" checked' in res.data

    # The plugin form's own validators run when the browser is saved
    before = len(datastore.browser_config_store.all())
    _add_browser(client, "Bad choice", "html_playwright_builtin", browser_type='chromium',
                 **{'plugin_test_lifecycle-mode': 'bogus'})
    res = _add_browser(client, "Long note", "html_playwright_builtin", browser_type='chromium',
                       **{'plugin_test_lifecycle-note': 'far too long a note'})
    assert len(datastore.browser_config_store.all()) == before
    assert b'Field cannot be longer than 10 characters' in res.data


def test_settings_of_missing_plugins_survive_a_save(client, live_server, measure_memory_usage, datastore_path, lifecycle_plugin):
    datastore = client.application.config.get('DATASTORE')
    cid = datastore.browser_config_store.add(label="Kept", base_fetcher="html_playwright_builtin",
                                             browser_config={'browser_type': 'chromium',
                                                             'plugin_settings': {'uninstalled_plugin': {'x': 1}}})
    client.post(url_for("ui.browser_config.browser_config_edit", config_id=cid),
                data={'label': 'Kept', 'browser_type': 'chromium', 'plugin_test_lifecycle-mode': 'always'},
                follow_redirects=True)
    stored = datastore.browser_config_store.get(cid)['browser_config']['plugin_settings']
    assert stored['uninstalled_plugin'] == {'x': 1}
    assert stored[PLUGIN_ID]['mode'] == 'always'


def test_plugin_section_on_its_own_tab_and_a_broken_plugin(client, live_server, measure_memory_usage, datastore_path):
    class OwnTab:
        @hookimpl
        def browser_config_form_section(self, base_fetcher, capabilities):
            return BrowserConfigSection(plugin_id='own_tab', label='My plugin tab', form_class=_ModeForm, tab='mine')

    class Broken:
        @hookimpl
        def browser_config_form_section(self, base_fetcher, capabilities):
            raise RuntimeError("broken plugin")

    plugin_manager.register(OwnTab(), name='test_own_tab')
    plugin_manager.register(Broken(), name='test_broken_section')
    try:
        res = client.get(url_for("ui.browser_config.browser_config_add", base_fetcher="html_playwright_builtin"))
        assert res.status_code == 200, "a raising plugin must not break the page"
        assert b'<a href="#plugin-tab-own_tab">My plugin tab</a>' in res.data
        assert b'id="plugin-tab-own_tab"' in res.data
    finally:
        plugin_manager.unregister(name='test_own_tab')
        plugin_manager.unregister(name='test_broken_section')


# --- At fetch time ---

def test_plugin_cookies_and_headers_reach_a_real_request(client, live_server, measure_memory_usage, datastore_path):
    """Through the plain HTTP client against a real endpoint that echoes the request headers."""
    class AddsCookie:
        @hookimpl
        def browser_request_alter(self, request):
            request.headers['X-From-Plugin'] = 'present'
            request.cookies.append({'name': 'plugin_cookie', 'value': 'sweet'})

    plugin_manager.register(AddsCookie(), name='test_adds_cookie')
    try:
        datastore = client.application.config.get('DATASTORE')
        uuid = datastore.add_watch(url=url_for('test_headers', _external=True), extras={'fetch_backend': 'html_requests'})
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        watch = datastore.data['watching'][uuid]
        snapshot = watch.get_history_snapshot(timestamp=watch.newest_history_key)
        assert 'X-From-Plugin:present' in snapshot
        assert 'Cookie:plugin_cookie=sweet' in snapshot
    finally:
        plugin_manager.unregister(name='test_adds_cookie')


def _check_and_wait(client, datastore, uuid, until, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        if until(datastore.data['watching'][uuid]):
            return datastore.data['watching'][uuid]
        time.sleep(0.2)
    raise AssertionError("condition not reached")


@pytest.mark.skipif(not os.getenv('ENABLE_DEBUG_CONTENT_FETCHER'),
                    reason="Needs ENABLE_DEBUG_CONTENT_FETCHER (set in the test-browser-config CI step)")
def test_full_lifecycle_through_a_check(client, live_server, measure_memory_usage, datastore_path, lifecycle_plugin):
    """The saved setting reaches the plugin at fetch time, its headers/cookies/proxy reach the
    engine (the debug engine echoes them), and the finished callback knows which engine ran."""
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, "Debug solver", "html_debug_test_browser", **{'plugin_test_lifecycle-mode': 'always'})
    cid = _browser_id(datastore, "Debug solver")
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': cid})

    def has_debug_snapshot(watch):
        return watch.history_n and 'debug_test_browser' in watch.get_history_snapshot(timestamp=watch.newest_history_key)
    watch = _check_and_wait(client, datastore, uuid, has_debug_snapshot)
    snapshot = watch.get_history_snapshot(timestamp=watch.newest_history_key)

    assert '"X-Test-Lifecycle": "yes"' in snapshot
    assert '"name": "cf_test"' in snapshot and url_for('test_endpoint', _external=True) in snapshot
    assert '"proxy": "http://plugin-proxy.example:3128"' in snapshot

    assert ('check', 'html_debug_test_browser', {'mode': 'always', 'note': None, 'enabled': False}) in lifecycle_plugin.altered
    done = [f for f in lifecycle_plugin.finished if f['fetcher_name'] == 'html_debug_test_browser']
    assert done and done[-1]['token'] == 123 and done[-1]['error'] is None and done[-1]['had_fetcher']


@pytest.mark.skipif(not os.getenv('ENABLE_DEBUG_CONTENT_FETCHER'),
                    reason="Needs ENABLE_DEBUG_CONTENT_FETCHER (set in the test-browser-config CI step)")
def test_a_plugin_can_stop_the_fetch_with_its_own_error(client, live_server, measure_memory_usage, datastore_path, lifecycle_plugin):
    datastore = client.application.config.get('DATASTORE')
    _add_browser(client, "Failing solver", "html_debug_test_browser", **{'plugin_test_lifecycle-mode': 'fail'})
    cid = _browser_id(datastore, "Failing solver")
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'fetch_backend': cid})

    watch = _check_and_wait(client, datastore, uuid, lambda w: w.get('last_error'))
    assert 'The test solver is unavailable' in watch.get('last_error')
    assert not watch.history_n, "nothing was fetched"


def test_plugin_settings_must_be_small_plain_json(client, live_server, measure_memory_usage, datastore_path):
    """Hosted users can type anything into a plugin's free-text field; it must not bloat
    browsers.json, and a non-JSON field type must not crash the save."""
    from decimal import Decimal
    from wtforms import TextAreaField

    class BigText(Form):
        text = TextAreaField('Text')

    class Plugin:
        @hookimpl
        def browser_config_form_section(self, base_fetcher, capabilities):
            return BrowserConfigSection(plugin_id='big_text', label='Big text', form_class=BigText)

    plugin_manager.register(Plugin(), name='test_big_text')
    try:
        datastore = client.application.config.get('DATASTORE')
        before = len(datastore.browser_config_store.all())
        res = _add_browser(client, "Bloated", "html_playwright_builtin", browser_type='chromium',
                           **{'plugin_big_text-text': 'x' * 20000})
        assert len(datastore.browser_config_store.all()) == before
        assert b'larger than 16 KB' in res.data
    finally:
        plugin_manager.unregister(name='test_big_text')

    from changedetectionio.browser_lifecycle import section_settings_error
    assert section_settings_error({'amount': Decimal('1.5')})
    assert section_settings_error({'mode': 'always', 'n': 3, 'on': True, 'list': ['a']}) is None


def test_plugin_can_supply_the_page_instead_of_the_browser(client, live_server, measure_memory_usage, datastore_path):
    """request.response = BrowserResponse(...) skips the browser; the status-code rules still apply."""
    from changedetectionio.plugin_api import BrowserResponse
    state = {'status': 200}

    class SuppliesPage:
        @hookimpl
        def browser_request_alter(self, request):
            request.response = BrowserResponse(content='<html><body>Page from the plugin</body></html>',
                                               status_code=state['status'])

    plugin_manager.register(SuppliesPage(), name='test_supplies_page')
    try:
        datastore = client.application.config.get('DATASTORE')
        # Nothing listens on this port: had the browser run, the check would fail to connect
        uuid = datastore.add_watch(url='http://127.0.0.1:1/never-fetched', extras={'fetch_backend': 'html_requests'})
        watch = _check_and_wait(client, datastore, uuid, lambda w: w.history_n)
        assert 'Page from the plugin' in watch.get_history_snapshot(timestamp=watch.newest_history_key)
        assert not watch.get('last_error')

        state['status'] = 403
        watch = _check_and_wait(client, datastore, uuid, lambda w: w.get('last_error'))
        assert '403' in str(watch.get('last_error'))
    finally:
        plugin_manager.unregister(name='test_supplies_page')


def test_log_says_what_plugins_changed_without_secrets():
    from requests.structures import CaseInsensitiveDict
    from changedetectionio.browser_lifecycle import _request_snapshot, describe_request_changes
    from changedetectionio.plugin_api import BrowserResponse

    request = BrowserRequest(url='https://example.com', fetcher_name='html_webdriver', fetcher_class=None,
                             browser_config=None, headers=CaseInsensitiveDict({'Accept': 'text/html'}),
                             proxy_url=None)
    before = _request_snapshot(request)
    request.headers['User-Agent'] = 'Solver UA'
    request.headers['Authorization'] = 'Bearer top-secret'
    request.cookies.append({'name': 'cf_clearance', 'value': 'cookie-secret'})
    request.proxy_url = 'http://user:proxy-secret@proxy.example:3128'
    request.response = BrowserResponse(content='x', status_code=200)
    summary = '; '.join(describe_request_changes(before, request))

    assert "user-agent='Solver UA'" in summary and 'authorization' in summary
    assert '1 cookie(s) [cf_clearance]' in summary
    assert 'proxy.example' in summary and 'supplied the page' in summary
    for secret in ('top-secret', 'cookie-secret', 'proxy-secret'):
        assert secret not in summary
    assert describe_request_changes(_request_snapshot(request), request)[-1].startswith('supplied'), \
        "nothing else changed since the second snapshot"
