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
    assert b'id="group-notification-settings" class=""' in res.data, "Notifications are not muted, so not dimmed"
    group['notification_muted'] = True
    assert b'id="group-notification-settings" class="group-setting-off"' in client.get(url_for("tags.form_tag_edit", uuid=group_uuid)).data
    group['notification_muted'] = False
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

    client.get(url_for("ui.form_watch_checknow", uuid=watch_uuid), follow_redirects=True)
    wait_for_all_checks(client)
    assert not watch.get('last_error'), "Fetched with the group's fetch method"
    assert watch.history_n >= 1
