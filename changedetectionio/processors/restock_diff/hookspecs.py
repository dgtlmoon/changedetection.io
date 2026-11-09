"""
Plugin hooks of the restock_diff processor, added to the plugin manager by register_plugin_hooks() in
__init__.py. The built-in implementations (plugins/default_charts.py, plugins/mark_viewed.py) are trylast, so a
plugin that implements one of these replaces the built-in.

The two chart hooks get the same arguments, take only the ones you need:
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


@hookspec(firstresult=True)
def restock_diff_mark_watch_viewed(watch, datastore):
    """A restock watch's history page, or its chart under the watch list row, was opened. The built-in saves
    that as the watch's last view, so the row stops showing as unviewed.

    Return anything but None to replace the built-in, None leaves it to the next plugin / the built-in.
    """
