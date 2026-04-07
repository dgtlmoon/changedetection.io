from changedetectionio.pluggy_interface import get_fetcher_capabilities


def _configure_extra_browser(datastore, name='custom browser URL'):
    datastore.data['settings']['requests']['extra_browsers'] = [
        {'browser_name': name, 'browser_connection_url': 'ws://sockpuppetbrowser-custom-url:3000'}
    ]
    return name


def test_capabilities_resolve_watch_extra_browser(client):
    datastore = client.application.config.get('DATASTORE')
    browser_name = _configure_extra_browser(datastore)

    uuid = datastore.add_watch(
        url='https://example.com',
        extras={'fetch_backend': f'extra_browser_{browser_name}', 'paused': True},
    )
    watch = datastore.data['watching'][uuid]

    capabilities = get_fetcher_capabilities(watch, datastore)

    assert capabilities['supports_screenshots'] is True
    assert capabilities['supports_xpath_element_data'] is True
    assert watch.fetcher_supports_screenshots is True


def test_capabilities_resolve_system_extra_browser_default(client):
    datastore = client.application.config.get('DATASTORE')
    browser_name = _configure_extra_browser(datastore)
    datastore.data['settings']['application']['fetch_backend'] = f'extra_browser_{browser_name}'

    uuid = datastore.add_watch(
        url='https://example.com', extras={'fetch_backend': 'system', 'paused': True}
    )
    watch = datastore.data['watching'][uuid]

    capabilities = get_fetcher_capabilities(watch, datastore)

    assert capabilities['supports_screenshots'] is True
    assert capabilities['supports_xpath_element_data'] is True
    assert watch.fetcher_supports_screenshots is True
