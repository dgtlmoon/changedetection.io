#!/usr/bin/env python3
"""A group can choose the fetch method (browser) and proxy for its watches. Off by default: a group changes
nothing until it is switched on, then it is either a fallback for watches with none of their own, or it is used
instead of the watch's own. See model/group_settings.py and the fetch_route_alter hook."""

import pytest
from flask import url_for

from changedetectionio.content_fetchers import resolve_content_fetcher
from changedetectionio.plugin_api import hookimpl
from changedetectionio.pluggy_interface import plugin_manager, resolve_fetch_route
from .util import set_original_response, wait_for_all_checks, delete_all_watches


@pytest.fixture
def setup(client, live_server, datastore_path):
    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    datastore.data['settings']['requests']['extra_proxies'] = [
        {'proxy_name': 'one', 'proxy_url': 'http://127.0.0.1:1'},
        {'proxy_name': 'two', 'proxy_url': 'http://127.0.0.1:2'},
    ]
    datastore.data['settings']['requests']['proxy'] = None
    yield datastore
    datastore.data['settings']['requests']['extra_proxies'] = []
    datastore.data['settings']['application']['tags'].clear()
    delete_all_watches(client)


def _proxy_key(datastore, name):
    return next(key for key, proxy in datastore.proxy_list.items() if proxy['label'] == name)


def _group(datastore, title, **settings):
    uuid = datastore.add_tag(title=title)
    group = datastore.data['settings']['application']['tags'][uuid]
    group.update(settings)
    return uuid, group


def _watch(datastore, tags=(), **settings):
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True, **settings})
    watch = datastore.data['watching'][uuid]
    watch['tags'] = list(tags)
    return uuid, watch


def test_group_does_nothing_until_switched_on(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    proxy_one, proxy_two = _proxy_key(datastore, 'one'), _proxy_key(datastore, 'two')

    # A new group is off for both
    group_uuid, group = _group(datastore, 'Shops')
    assert group['fetch_backend_group_mode'] == 'off' and group['proxy_group_mode'] == 'off'

    # Set up but not switched on, and a group saved before the setting existed, change nothing
    group.update({'fetch_backend': 'html_webdriver', 'proxy': proxy_two})
    _, old_group = _group(datastore, 'From an older version', fetch_backend='html_webdriver', proxy=proxy_two)
    del old_group['fetch_backend_group_mode']
    del old_group['proxy_group_mode']

    watch_uuid, watch = _watch(datastore, tags=[group_uuid, old_group['uuid']])
    route = resolve_fetch_route(watch, datastore)
    assert route == {'fetch_backend': 'system', 'proxy': None, 'changed_by': {}}
    assert resolve_content_fetcher(watch, datastore)[1] == 'html_requests'
    assert datastore.get_preferred_proxy_for_watch(watch_uuid) == proxy_one, "System default, the first proxy"

    watch.update({'fetch_backend': 'html_requests', 'proxy': proxy_one})
    route = resolve_fetch_route(watch, datastore)
    assert (route['fetch_backend'], route['proxy'], route['changed_by']) == ('html_requests', proxy_one, {})


def test_group_fetch_backend_modes(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    group_uuid, group = _group(datastore, 'Shops', fetch_backend='html_webdriver', fetch_backend_group_mode='fallback')
    _, on_default = _watch(datastore, tags=[group_uuid])
    _, has_own = _watch(datastore, tags=[group_uuid], fetch_backend='html_requests')
    _, not_in_group = _watch(datastore)

    # Only if the watch has none of its own
    route = resolve_fetch_route(on_default, datastore)
    assert route['fetch_backend'] == 'html_webdriver'
    assert route['changed_by']['fetch_backend'] == {'label': group['title'], 'group_uuid': group_uuid, 'replaces_watch': False}
    assert resolve_content_fetcher(on_default, datastore)[1] == 'html_webdriver'
    assert on_default.get_fetch_backend == 'html_webdriver', "Pages ask the watch, same answer as the check"

    route = resolve_fetch_route(has_own, datastore)
    assert route['fetch_backend'] == 'html_requests' and not route['changed_by']

    # Instead of the watch's own
    group['fetch_backend_group_mode'] = 'replace'
    route = resolve_fetch_route(has_own, datastore)
    assert route['fetch_backend'] == 'html_webdriver'
    assert route['changed_by']['fetch_backend']['replaces_watch'] is True
    assert has_own['fetch_backend'] == 'html_requests', "The watch keeps its own choice for when the group stops deciding"

    assert resolve_fetch_route(not_in_group, datastore)['fetch_backend'] == 'system'

    # Switched off again
    group['fetch_backend_group_mode'] = 'off'
    assert resolve_fetch_route(on_default, datastore)['fetch_backend'] == 'system'
    assert resolve_fetch_route(has_own, datastore)['fetch_backend'] == 'html_requests'

    # Switched on with nothing chosen is the same as off
    group.update({'fetch_backend_group_mode': 'replace', 'fetch_backend': 'system'})
    assert resolve_fetch_route(has_own, datastore)['fetch_backend'] == 'html_requests'


def test_group_proxy_modes(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    proxy_one, proxy_two = _proxy_key(datastore, 'one'), _proxy_key(datastore, 'two')

    group_uuid, group = _group(datastore, 'Shops', proxy=proxy_two, proxy_group_mode='fallback')
    on_default_uuid, on_default = _watch(datastore, tags=[group_uuid])
    has_own_uuid, has_own = _watch(datastore, tags=[group_uuid], proxy=proxy_one)

    assert datastore.get_preferred_proxy_for_watch(on_default_uuid) == proxy_two
    assert datastore.get_preferred_proxy_for_watch(has_own_uuid) == proxy_one
    assert resolve_fetch_route(on_default, datastore)['changed_by']['proxy']['group_uuid'] == group_uuid

    group['proxy_group_mode'] = 'replace'
    assert datastore.get_preferred_proxy_for_watch(has_own_uuid) == proxy_two

    # A group can send its watches direct
    group['proxy'] = 'no-proxy'
    assert resolve_fetch_route(has_own, datastore)['proxy'] == 'no-proxy'
    assert datastore.get_preferred_proxy_for_watch(has_own_uuid) is None

    # A proxy that was removed from the list is not a choice any more
    group['proxy'] = 'ui-0gone'
    assert datastore.get_preferred_proxy_for_watch(has_own_uuid) == proxy_one
    assert not resolve_fetch_route(has_own, datastore)['changed_by']

    # The browser and the proxy are switched on separately
    group.update({'proxy': proxy_two, 'fetch_backend': 'html_webdriver'})
    route = resolve_fetch_route(on_default, datastore)
    assert route['proxy'] == proxy_two and route['fetch_backend'] == 'system'


def test_watch_in_several_groups(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    first_uuid, first = _group(datastore, 'First', fetch_backend='html_webdriver', fetch_backend_group_mode='fallback')
    second_uuid, second = _group(datastore, 'Second', fetch_backend='html_requests', fetch_backend_group_mode='fallback')
    off_uuid, _ = _group(datastore, 'Off', fetch_backend='html_requests')

    # The first group in the watch's own list that is switched on
    _, watch = _watch(datastore, tags=[off_uuid, second_uuid, first_uuid])
    assert resolve_fetch_route(watch, datastore)['changed_by']['fetch_backend']['group_uuid'] == second_uuid
    watch['tags'] = [off_uuid, first_uuid, second_uuid]
    assert resolve_fetch_route(watch, datastore)['changed_by']['fetch_backend']['group_uuid'] == first_uuid

    # "Instead of the watch's own" comes before "only if the watch has none", wherever it is in the list
    second['fetch_backend_group_mode'] = 'replace'
    assert resolve_fetch_route(watch, datastore)['changed_by']['fetch_backend']['group_uuid'] == second_uuid

    # A group applied by its URL pattern counts too, after the ones the watch was put in
    by_url_uuid, _ = _group(datastore, 'By URL', fetch_backend='html_webdriver', fetch_backend_group_mode='fallback',
                            url_match_pattern='*test-endpoint*')
    _, other_watch = _watch(datastore)
    assert resolve_fetch_route(other_watch, datastore)['changed_by']['fetch_backend']['group_uuid'] == by_url_uuid


def test_fetch_route_alter_hook_for_plugins(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    proxy_two = _proxy_key(datastore, 'two')
    _, watch = _watch(datastore, fetch_backend='html_requests')

    class Plugin:
        proxy = proxy_two

        @hookimpl
        def fetch_route_alter(self, watch, datastore, route):
            route['fetch_backend'] = 'html_webdriver'
            route['proxy'] = self.proxy
            route['changed_by']['fetch_backend'] = {'label': 'A plugin'}
            route['changed_by']['proxy'] = {'label': 'A plugin'}

    plugin = Plugin()
    plugin_manager.register(plugin, name='test_fetch_route_alter')
    try:
        route = resolve_fetch_route(watch, datastore)
        assert (route['fetch_backend'], route['proxy']) == ('html_webdriver', proxy_two)
        assert resolve_content_fetcher(watch, datastore)[1] == 'html_webdriver'
        assert datastore.get_preferred_proxy_for_watch(watch['uuid']) == proxy_two

        # A proxy URL (or anything else not in the configured list) is never accepted
        plugin.proxy = 'http://evil.example:8080'
        route = resolve_fetch_route(watch, datastore)
        assert route['proxy'] is None and 'proxy' not in route['changed_by']
        assert route['fetch_backend'] == 'html_webdriver'
    finally:
        plugin_manager.unregister(name='test_fetch_route_alter')

    assert resolve_fetch_route(watch, datastore)['fetch_backend'] == 'html_requests'


def test_group_request_and_proxy_tabs_and_watch_edit_note(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    proxy_two = _proxy_key(datastore, 'two')
    group_uuid, group = _group(datastore, 'Shops <b>&</b> more')
    watch_uuid, watch = _watch(datastore, tags=[group_uuid], fetch_backend='html_requests')

    res = client.get(url_for("tags.form_tag_edit", uuid=group_uuid))
    assert res.data.count(b'group-setting-off" data-dimmed-while-off=') == 3, "Fetch method, proxy and recheck time are dimmed while off"
    # Notification settings: dimmed while they are only the fallback for a watch with none (the default), or muted
    assert b'id="group-notification-settings" class="group-setting-off"' in res.data
    group['notification_group_mode'] = 'add'
    assert b'id="group-notification-settings" class=""' in client.get(url_for("tags.form_tag_edit", uuid=group_uuid)).data
    group['notification_muted'] = True
    assert b'id="group-notification-settings" class="group-setting-off"' in client.get(url_for("tags.form_tag_edit", uuid=group_uuid)).data
    group['notification_muted'] = False
    group['notification_group_mode'] = 'fallback'
    assert b'name="fetch_backend_group_mode"' in res.data and b'name="proxy_group_mode"' in res.data
    assert b'href="#request"' in res.data and b'id="request"' in res.data, "The fetch method is on the Request tab"
    assert b'href="#proxy"' in res.data and b'id="proxy"' in res.data, "The proxy has its own tab"
    assert b"Don&#39;t use" in res.data or b"Don't use" in res.data

    # Nothing on the watch's page while the group is off
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    assert b'decided-elsewhere-note' not in res.data

    res = client.post(
        url_for("tags.form_tag_edit_submit", uuid=group_uuid),
        data={"title": group['title'], "fetch_backend": "html_webdriver", "fetch_backend_group_mode": "replace",
              "proxy": proxy_two, "proxy_group_mode": "fallback"},
        follow_redirects=True,
    )
    assert b"Updated" in res.data
    assert (group['fetch_backend'], group['fetch_backend_group_mode']) == ('html_webdriver', 'replace')
    assert (group['proxy'], group['proxy_group_mode']) == (proxy_two, 'fallback')

    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    group_link = url_for('tags.form_tag_edit', uuid=group_uuid).encode()
    assert b'Decided by group <a href="' + group_link + b'#request"' in res.data, "The fetch method names the group, with a link to its Request tab"
    assert b'From group <a href="' + group_link + b'#proxy"' in res.data, "So does the proxy, as a fallback"
    assert b'decided_fetch_backend="html_webdriver"' in res.data
    # The group's name is text, not markup
    assert b'<b>&</b> more' not in res.data and b'&lt;b&gt;&amp;&lt;/b&gt; more' in res.data

    # Saving the watch does not lose its own choice
    assert watch['fetch_backend'] == 'html_requests'

    # "Not set" for the proxy is stored as no choice
    client.post(
        url_for("tags.form_tag_edit_submit", uuid=group_uuid),
        data={"title": group['title'], "fetch_backend": "system", "fetch_backend_group_mode": "off",
              "proxy": "", "proxy_group_mode": "off"},
        follow_redirects=True,
    )
    assert group['proxy'] is None and group['fetch_backend'] == 'system'
    res = client.get(url_for("ui.ui_edit.edit_page", uuid=watch_uuid))
    assert b'decided-elsewhere-note' not in res.data


def test_group_fetch_backend_is_what_the_check_uses(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    set_original_response(datastore_path=datastore_path)
    # No proxies for this one, it really fetches
    datastore.data['settings']['requests']['extra_proxies'] = []
    # The watch asks for a browser that is not there, its group says use the plain fetcher instead
    group_uuid, group = _group(datastore, 'Shops', fetch_backend='html_requests', fetch_backend_group_mode='replace')
    # Paused until it is in its group: a watch that can be checked is picked up straight away, and one checked
    # before its group was attached went to the browser that is not there
    watch_uuid, watch = _watch(datastore, tags=[group_uuid], fetch_backend='html_webdriver')
    watch['paused'] = False

    client.post(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
    wait_for_all_checks(client)
    assert not watch.get('last_error'), "Fetched with the group's fetch method"
    assert watch.history_n >= 1


def test_group_edit_says_which_group_a_watch_follows(client, live_server, measure_memory_usage, datastore_path, setup):
    """Fetch method, proxy and recheck time come from one group only. The tabs that set them say which, at the bottom."""
    import re
    datastore = setup
    group_uuid, group = _group(datastore, 'Shops')
    note = 'Note: a watch in several groups follows the first group in its list that has this switched on.'

    page = client.get(url_for("tags.form_tag_edit", uuid=group_uuid)).get_data(as_text=True)
    for tab in ('request', 'proxy', 'recheck-time'):
        pane = re.search(r'<div class="tab-pane-inner" id="%s">(.*?)</fieldset>' % tab, page, re.S).group(1)
        assert note in pane, f"The {tab} tab has the note"
        assert pane.rstrip().endswith('</div>') and note in pane[-400:], f"At the bottom of the {tab} tab"
    assert page.count(note) == 3, "Not on the tabs whose settings every group of a watch adds to (filters, notifications ...)"

    # And that is the rule: two groups switched on, the first in the watch's list is followed
    second_uuid, second = _group(datastore, 'Second', fetch_backend='html_webdriver', fetch_backend_group_mode='replace')
    group.update({'fetch_backend': 'html_requests', 'fetch_backend_group_mode': 'replace'})
    watch_uuid, watch = _watch(datastore, tags=[group_uuid, second_uuid])
    assert resolve_fetch_route(watch, datastore)['fetch_backend'] == 'html_requests'
    watch['tags'] = [second_uuid, group_uuid]
    assert resolve_fetch_route(watch, datastore)['fetch_backend'] == 'html_webdriver'


def test_watch_list_fetcher_icon_follows_watch_then_group_then_system(client, live_server, measure_memory_usage, datastore_path, setup):
    import re
    datastore = setup
    basic, browser = 'basic-fetcher.svg', 'google-chrome-icon.png'
    fallback_uuid, fallback_group = _group(datastore, 'Fallback', fetch_backend='html_webdriver', fetch_backend_group_mode='fallback')
    replace_uuid, replace_group = _group(datastore, 'Replace', fetch_backend='html_requests', fetch_backend_group_mode='replace')

    on_system, _ = _watch(datastore)
    own_basic, _ = _watch(datastore, fetch_backend='html_requests')
    own_browser, _ = _watch(datastore, fetch_backend='html_webdriver')
    group_fallback, _ = _watch(datastore, tags=[fallback_uuid])
    own_beats_fallback, _ = _watch(datastore, tags=[fallback_uuid], fetch_backend='html_requests')
    group_replaces_own, _ = _watch(datastore, tags=[replace_uuid], fetch_backend='html_webdriver')

    def icons():
        html = client.get(url_for("watchlist.index")).data.decode()
        rows = {}
        for uuid in datastore.data['watching']:
            row = re.search(rf'<tr id="{uuid}".*?</tr>', html, re.DOTALL).group(0)
            rows[uuid] = (basic in row, browser in row)
        return rows

    rows = icons()
    assert rows[on_system] == (True, False), "Nothing set anywhere, the system default"
    assert rows[own_basic] == (True, False)
    assert rows[own_browser] == (False, True)
    assert rows[group_fallback] == (False, True), "None of its own, its group decides"
    assert rows[own_beats_fallback] == (True, False), "A fallback group leaves the watch's own choice"
    assert rows[group_replaces_own] == (True, False), "The group is used instead of the watch's own"
    assert b'title="Using basic HTTP fetcher"' in client.get(url_for("watchlist.index")).data

    # The system default changes, only the watches left on it follow
    datastore.data['settings']['application']['fetch_backend'] = 'html_webdriver'
    rows = icons()
    assert rows[on_system] == (False, True)
    assert rows[own_basic] == (True, False)
    assert rows[group_replaces_own] == (True, False)

    # Groups switched off, back to the watch's own and then the system default
    fallback_group['fetch_backend_group_mode'] = 'off'
    replace_group['fetch_backend_group_mode'] = 'off'
    rows = icons()
    assert rows[group_fallback] == (False, True), "System default, a browser now"
    assert rows[group_replaces_own] == (False, True), "Its own choice again"
    datastore.data['settings']['application']['fetch_backend'] = 'html_requests'
    assert icons()[group_fallback] == (True, False)


def test_fetch_method_options_show_the_fetcher_icon(client, live_server, measure_memory_usage, datastore_path, setup):
    import re
    datastore = setup
    group_uuid, _ = _group(datastore, 'Shops')
    watch_uuid, _ = _watch(datastore)

    def option_icons(url, field_id='fetch_backend'):
        html = client.get(url).data.decode()
        field = re.search(rf'<ul[^>]*id="{field_id}".*?</ul>', html, re.DOTALL).group(0)
        # value -> its label, an option without an icon is the text alone (no empty space left for one)
        return dict(re.findall(r'value="([^"]+)">\s*<label[^>]*>(.*?)</label>', field))

    for url, field_id, unset in ((url_for("ui.ui_edit.edit_page", uuid=watch_uuid), 'fetch_backend', 'system'),
                                 (url_for("tags.form_tag_edit", uuid=group_uuid), 'fetch_backend', 'system'),
                                 (url_for("settings.settings_page"), 'application-fetch_backend', None)):
        icons = option_icons(url, field_id)
        assert '<span class="fetcher-option-icon"><img' in icons['html_requests'], url
        assert 'basic-fetcher.svg' in icons['html_requests'], url
        assert 'title="Using basic HTTP fetcher"' in icons['html_requests'], url
        assert 'google-chrome-icon.png' in icons['html_webdriver'], url
        if unset:
            assert 'fetcher-option-icon' not in icons[unset] and '<img' not in icons[unset], url

    # The same list in the watch list's 'Browser' dialog
    html = client.get(url_for("watchlist.index")).data.decode()
    dialog = re.search(r'<template id="bulk-browser-options">.*?</template>', html, re.DOTALL).group(0)
    assert re.search(r'value="html_requests"> <span class="fetcher-option-icon"><img[^>]*basic-fetcher\.svg', dialog)
    assert re.search(r'value="system" checked> [^<]', dialog), "No icon, no space for one"


def test_group_fetch_backend_that_was_removed_is_an_error_on_the_watch(client, live_server, measure_memory_usage, datastore_path, setup):
    datastore = setup
    set_original_response(datastore_path=datastore_path)
    datastore.data['settings']['requests']['extra_proxies'] = []

    # A fetcher whose plugin is no longer installed, and a custom browser endpoint that was deleted
    for removed in ('html_plugin_that_was_uninstalled', 'extra_browser_deleted'):
        group_uuid, group = _group(datastore, f'Shops {removed}', fetch_backend=removed, fetch_backend_group_mode='replace')
        watch_uuid, watch = _watch(datastore, tags=[group_uuid], fetch_backend='html_requests')
        watch['paused'] = False

        client.post(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
        wait_for_all_checks(client)
        expected = f"Group 'Shops {removed}' tried to use fetch method '{removed}' but it doesn't exist, please fix the group"
        assert watch.get('last_error') == expected
        assert watch.history_n == 0, "Not fetched with some other fetcher"
        # ..where it is seen, in the watch list
        assert expected.replace("'", "&#39;").encode() in client.get(url_for("watchlist.index")).data

        # The group fixed, the next check goes through
        group['fetch_backend'] = 'html_requests'
        client.post(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
        wait_for_all_checks(client)
        assert not watch.get('last_error') and watch.history_n == 1
        watch['paused'] = True

    # A watch's own fetch method that is gone is not a group's doing, it is fetched as it always was
    watch_uuid, watch = _watch(datastore, fetch_backend='html_plugin_that_was_uninstalled')
    watch['paused'] = False
    client.post(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
    wait_for_all_checks(client)
    assert not watch.get('last_error') and watch.history_n == 1


def test_group_proxy_that_was_removed_is_an_error_on_the_watch(client, live_server, measure_memory_usage, datastore_path, setup):
    from changedetectionio.model.group_settings import group_with_proxy_that_is_gone
    datastore = setup
    set_original_response(datastore_path=datastore_path)
    proxy_one = _proxy_key(datastore, 'one')

    group_uuid, group = _group(datastore, 'Shops', proxy='ui-0gone', proxy_group_mode='replace')
    off_uuid, _ = _group(datastore, 'Off', proxy='ui-0gone')
    not_set_uuid, _ = _group(datastore, 'Nothing chosen', proxy=None, proxy_group_mode='replace')
    direct_uuid, _ = _group(datastore, 'Direct', proxy='no-proxy', proxy_group_mode='replace')

    def gone(tags=(), **settings):
        choice = group_with_proxy_that_is_gone(_watch(datastore, tags=tags, **settings)[1], datastore)
        return choice.group['uuid'] if choice else None

    assert gone(tags=[group_uuid]) == group_uuid
    assert gone(tags=[group_uuid], proxy=proxy_one) == group_uuid, "Used instead of the watch's own"
    # Not a group that is not used, has nothing chosen, or says no proxy
    assert gone(tags=[off_uuid, not_set_uuid, direct_uuid]) is None
    assert gone() is None
    # Only a fallback: the watch that has its own is not this group's
    group['proxy_group_mode'] = 'fallback'
    assert gone(tags=[group_uuid], proxy=proxy_one) is None
    assert gone(tags=[group_uuid]) == group_uuid
    group['proxy_group_mode'] = 'replace'

    # The check says so on the watch and fetches nothing
    # (no proxy that works here, so the watch is only checked while its group is the problem)
    watch_uuid, watch = _watch(datastore, tags=[group_uuid])
    watch['paused'] = False
    client.post(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
    wait_for_all_checks(client)
    expected = "Group 'Shops' tried to use proxy key 'ui-0gone' but it doesn't exist anymore, please fix the group"
    assert watch.get('last_error') == expected
    assert watch.history_n == 0
    assert expected.replace("'", "&#39;").encode() in client.get(url_for("watchlist.index")).data
    watch['paused'] = True

    # A proxy for this one check only (the proxy checker, a recheck through another proxy) is not the group's
    from changedetectionio.processors.base import difference_detection_processor
    processor = difference_detection_processor(datastore, watch_uuid)
    processor.queued_metadata = {'proxy': proxy_one}
    assert processor._proxy_for_this_check() == proxy_one
    processor.queued_metadata = {'proxy': 'no-proxy'}
    assert processor._proxy_for_this_check() is None

    # The group fixed
    group['proxy'] = proxy_one
    processor.queued_metadata = {}
    assert processor._proxy_for_this_check() == proxy_one
