#!/usr/bin/env python3
"""The restock price/stock charts come from the restock_diff plugin hooks
restock_diff_watchlist_overview_chart / restock_diff_watch_history_page_chart: the built-in chart is the
trylast default, a plugin implementing either hook replaces that chart."""
import json
import re

import pytest
from flask import url_for

from ..util import wait_for_all_checks, delete_all_watches, import_example_plugin
from .test_restock import set_price_response


def add_restock_watch_with_two_prices(client, datastore_path):
    set_price_response(datastore_path=datastore_path, price="100.00")
    client.post(url_for("ui.ui_views.form_quick_watch_add"),
                data={"url": url_for('test_endpoint', _external=True), "tags": '', 'processor': 'restock_diff',
                      'fetch_backend': 'html_requests'}, follow_redirects=True)
    wait_for_all_checks(client)
    set_price_response(datastore_path=datastore_path, price="82.00")
    client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    return next(iter(client.application.config.get('DATASTORE').data['watching']))


def chart(client, uuid, context):
    return client.get(url_for('ui.ui_diff.diff_history_page_processor_chart', uuid=uuid, context=context))


def test_restock_default_charts(client, live_server, measure_memory_usage, datastore_path):
    uuid = add_restock_watch_with_two_prices(client, datastore_path)

    for context, height in (('history', 320), ('watchlist', 230)):
        res = chart(client, uuid, context)
        assert res.status_code == 200
        assert res.headers['Content-Type'].startswith('text/html')
        assert b'class="restock-graph-default"' in res.data
        assert f'data-height="{height}"'.encode() in res.data
        series = json.loads(re.search(r"data-series='([^']*)'", res.data.decode()).group(1))
        assert [p['price'] for p in series] == [100.0, 82.0]

    assert chart(client, uuid, 'no-such-context').status_code == 404

    # Where the pages load them from
    res = client.get(url_for('ui.ui_diff.diff_history_page', uuid=uuid))
    assert b'window.restock_chart_url' in res.data
    assert b'processor-chart?context=history' in res.data
    res = client.get(url_for('watchlist.index'))
    assert b'data-processor-chart-url="' in res.data
    assert b'processor-chart?context=watchlist' in res.data

    delete_all_watches(client)


def test_restock_chart_hook_replaces_only_its_chart(client, live_server, measure_memory_usage, datastore_path):
    """A plugin implementing only the history page hook replaces that chart, the watch list one stays built-in."""
    from changedetectionio.pluggy_interface import plugin_manager, hookimpl

    class HistoryChartOnly:
        @hookimpl
        def restock_diff_watch_history_page_chart(self, series):
            return f'<p id="my-chart">{len(series)} points</p>'

    uuid = add_restock_watch_with_two_prices(client, datastore_path)
    plugin_manager.register(HistoryChartOnly(), 'test_history_chart_only')
    try:
        assert chart(client, uuid, 'history').data == b'<p id="my-chart">2 points</p>'
        assert b'restock-graph-default' in chart(client, uuid, 'watchlist').data
    finally:
        plugin_manager.unregister(name='test_history_chart_only')

    assert b'restock-graph-default' in chart(client, uuid, 'history').data, "Back to the built-in chart"
    delete_all_watches(client)


def test_text_watch_has_no_chart(client, live_server, measure_memory_usage, datastore_path):
    client.post(url_for("ui.ui_views.form_quick_watch_add"),
                data={"url": url_for('test_endpoint', _external=True), "tags": '', 'paused': 'y'}, follow_redirects=True)
    uuid = next(iter(client.application.config.get('DATASTORE').data['watching']))
    assert chart(client, uuid, 'history').status_code == 404
    delete_all_watches(client)


@pytest.fixture
def simple_svg_chart_plugin():
    from changedetectionio.pluggy_interface import plugin_manager
    plugin = import_example_plugin('restock/simple_svg_chart', 'cdio_example_simple_svg_chart')
    plugin_manager.register(plugin, 'cdio_example_simple_svg_chart')
    yield plugin
    plugin_manager.unregister(plugin)


def test_example_simple_svg_chart_plugin(client, live_server, measure_memory_usage, datastore_path, simple_svg_chart_plugin):
    uuid = add_restock_watch_with_two_prices(client, datastore_path)

    for context, height in (('history', 240), ('watchlist', 80)):
        res = chart(client, uuid, context)
        assert res.status_code == 200
        assert b'<figure class="cdio-example-simple-svg-chart">' in res.data
        assert f'height="{height}"'.encode() in res.data
        assert b'<polyline points="0.0,0.0 600.0,' in res.data, "100.00 then 82.00: starts at the top, ends lower"
        assert b'2 prices, lowest 82 USD, highest 100 USD' in res.data
        assert b'restock-graph-default' not in res.data

    # Listed under Settings > Info as an active plugin, with its docstring's first line
    res = client.get(url_for("settings.settings_page"))
    assert b'<li><strong>cdio_example_simple_svg_chart</strong> - Example plugin - replaces the restock price charts' in res.data

    delete_all_watches(client)
