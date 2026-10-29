"""The built-in restock price/stock charts, as the trylast implementation of the hooks in ../hookspecs.py,
so any other plugin implementing them wins. Drawn in the browser by static/js/restock-price-graph.js
from the data in templates/restock_diff/chart_default.html."""
from changedetectionio.plugin_api import hookimpl

# Shorter inline under the watch list row than on the history page
WATCHLIST_HEIGHT = 230
HISTORY_PAGE_HEIGHT = 320


def _render(series, currency, summary, height):
    from flask import render_template
    return render_template('restock_diff/chart_default.html',
                           series=series, currency=currency, summary=summary, height=height)


@hookimpl(trylast=True)
def restock_diff_watchlist_overview_chart(series, currency, summary):
    return _render(series, currency, summary, WATCHLIST_HEIGHT)


@hookimpl(trylast=True)
def restock_diff_watch_history_page_chart(series, currency, summary):
    return _render(series, currency, summary, HISTORY_PAGE_HEIGHT)
