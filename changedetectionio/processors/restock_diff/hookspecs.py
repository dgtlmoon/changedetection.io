"""
Plugin hooks of the restock_diff processor, added to the plugin manager by register_plugin_hooks() in
__init__.py. The built-in charts implement them in plugins/default_charts.py (trylast), so a plugin that
implements one of these replaces that chart.

Both get the same arguments, take only the ones you need:
    series:   [{'timestamp': <epoch sec>, 'price': <float or None>, 'in_stock': <bool or None>}, ...]
              oldest -> newest, one per history snapshot
    currency: e.g. 'USD', or '' when not known
    summary:  price statistics (see difference.compute_price_summary), or None with too little history
    watch:    the Watch model instance

Return the chart as an HTML string (or None to leave it to the next plugin / the built-in chart).
It's inserted into the page as-is, a <script> in it runs.
"""
from changedetectionio.pluggy_interface import hookspec


@hookspec(firstresult=True)
def restock_diff_watchlist_overview_chart(series, currency, summary, watch):
    """The chart that rolls down under a restock watch in the watch list (its History button)."""


@hookspec(firstresult=True)
def restock_diff_watch_history_page_chart(series, currency, summary, watch):
    """The chart on a restock watch's history (/diff) page."""
