#!/usr/bin/env python3
"""Plugins can add links to the left action sidebar with the register_sidebar_items hook."""
import pytest
from flask import url_for

from changedetectionio.pluggy_interface import hookimpl, plugin_manager


class _SidebarPlugin:
    @hookimpl
    def register_sidebar_items(self, datastore):
        return [
            {'label': 'Plugin page', 'endpoint': 'tags.tags_overview_page', 'icon': 'star',
             'active_prefix': 'tags.', 'title': 'A page from a plugin'},
            {'label': 'External', 'url': 'https://example.com/help', 'icon': 'help-circle', 'weight': -1},
            # Greyed out and not clickable, no endpoint needed
            {'label': 'Coming later', 'icon': 'clock', 'disabled': True, 'badge': 'soon', 'title': 'Coming later (soon)'},
            # A custom icon instead of a Feather one
            {'label': 'Own icon', 'url': '/own', 'svg': '<svg class="action-icon" id="test-own-svg" viewBox="0 0 24 24"></svg>'},
            # Bad entries are skipped, the page still renders
            {'label': 'No such endpoint', 'endpoint': 'nope.nothing'},
            {'no': 'label'},
            'not a dict',
        ]


@pytest.fixture
def sidebar_plugin():
    plugin = _SidebarPlugin()
    plugin_manager.register(plugin, name='test_sidebar_items')
    yield plugin
    plugin_manager.unregister(name='test_sidebar_items')


def test_plugin_sidebar_items(client, live_server, measure_memory_usage, datastore_path, sidebar_plugin):
    res = client.get(url_for('watchlist.index'))
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    tags_url = url_for('tags.tags_overview_page')
    assert f'href="{tags_url}"' in html and 'Plugin page' in html and 'data-feather="star"' in html
    assert 'title="A page from a plugin"' in html
    assert 'href="https://example.com/help"' in html
    # A disabled item renders like the built-in "Browsers (coming soon)" one
    assert ('<a href="#"\n           class="action-sidebar-item is-disabled"\n           title="Coming later (soon)"\n'
            '           aria-disabled="true"\n           tabindex="-1">') in html
    assert '<span class="action-badge">soon</span>' in html.split('Coming later (soon)')[1].split('</a>')[0]

    # A custom svg is rendered as-is, in place of the Feather icon
    own = html.split('href="/own"')[1].split('</a>')[0]
    assert '<svg class="action-icon" id="test-own-svg"' in own and 'data-feather' not in own

    # Each plugin item says which plugin added it, just before its <li>
    marker = f'<!-- blueprint:{_SidebarPlugin.__module__}._SidebarPlugin -->'
    assert html.count(marker) == 4 * 2, "four items, rendered in the desktop rail and the mobile drawer"
    assert html.split(marker)[1].lstrip().startswith('<li class="action-sidebar-li">')
    assert 'No such endpoint' not in html
    # Lower weight first
    assert html.index('External') < html.index('Plugin page')

    # Highlighted on its own page (the sidebar renders twice: desktop rail and mobile drawer)
    res = client.get(tags_url)
    html = res.get_data(as_text=True)
    assert html.count('class="action-sidebar-item active"\n           title="A page from a plugin"') == 2


def test_no_plugin_sidebar_items(client, live_server, measure_memory_usage, datastore_path):
    res = client.get(url_for('watchlist.index'))
    assert res.status_code == 200 and 'Plugin page' not in res.get_data(as_text=True)
