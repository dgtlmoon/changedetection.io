"""
Example plugin - replaces the restock price charts with a simple SVG line drawn on the server.

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
It is not active until installed (or registered), nothing scans example_plugins/ for plugins.
"""
from markupsafe import escape

from changedetectionio.plugin_api import hookimpl


def price_svg(series, currency, width, height):
    """A plain SVG line of the prices, no JavaScript needed. series is oldest -> newest."""
    prices = [p['price'] for p in series if p.get('price') is not None]
    if len(prices) < 2:
        return '<p class="cdio-example-simple-svg-chart">Not enough prices to draw a line yet.</p>'

    low, high = min(prices), max(prices)
    span = (high - low) or 1
    step = width / (len(prices) - 1)
    points = ' '.join(f"{i * step:.1f},{height - (price - low) / span * height:.1f}" for i, price in enumerate(prices))
    caption = f"{len(prices)} prices, lowest {low:g} {currency}, highest {high:g} {currency}".replace('  ', ' ')

    # This HTML goes into the page as-is, escape anything that isn't yours
    return (f'<figure class="cdio-example-simple-svg-chart">'
            f'<svg viewBox="0 -4 {width} {height + 8}" width="100%" height="{height}" preserveAspectRatio="none">'
            f'<polyline points="{points}" fill="none" stroke="currentColor" stroke-width="2"/></svg>'
            f'<figcaption>{escape(caption)}</figcaption></figure>')


@hookimpl
def restock_diff_watchlist_overview_chart(series, currency):
    """Replaces the chart under a restock watch in the watch list (its History button)."""
    return price_svg(series, currency, width=600, height=80)


@hookimpl
def restock_diff_watch_history_page_chart(series, currency):
    """Replaces the chart on a restock watch's history page."""
    return price_svg(series, currency, width=600, height=240)
