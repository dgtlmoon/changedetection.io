"""
Example plugin - times every check and shows the result in the watch list and on the edit page.

Install it with `pip install .` from the directory above this one, see example_plugins/README.md.
It is not active until installed (or registered), nothing scans example_plugins/ for plugins.

The stats are kept in memory only, so they start empty again after a restart.
"""
import os
import time

from markupsafe import escape

from changedetectionio.plugin_api import hookimpl

# Per watch uuid: {'duration': seconds, 'ok': bool, 'error': str or None, 'finished': unix time, 'count': int}
STATS = {}

# Where the handler keeps its start time between the two check hooks below
_STARTED_ATTR = '_cdio_example_check_stats_started'


@hookimpl
def update_handler_alter(update_handler, watch, datastore):
    """Called once a check is about to start, before the page is fetched."""
    setattr(update_handler, _STARTED_ATTR, time.monotonic())
    # None = keep the handler as it is, you could also return a wrapped one
    return None


@hookimpl
def update_finalize(update_handler, watch, datastore, processing_exception):
    """Called once the check is over, whether it worked or not."""
    started = getattr(update_handler, _STARTED_ATTR, None) if update_handler else None
    if started is None or not watch:
        return
    previous = STATS.get(watch.get('uuid'), {})
    STATS[watch.get('uuid')] = {
        'duration': time.monotonic() - started,
        'ok': processing_exception is None,
        'error': str(processing_exception) if processing_exception else None,
        'finished': time.time(),
        'count': previous.get('count', 0) + 1,
    }


@hookimpl
def watch_list_extra_text(watch):
    """A short note under the watch in the watch list. Called for every row, so in memory only."""
    stats = STATS.get(watch.get('uuid'))
    if not stats:
        return None
    if stats['ok']:
        return f"Last check took {stats['duration']:.2f}s"
    return f"Last check failed after {stats['duration']:.2f}s"


@hookimpl
def ui_edit_stats_extras(watch):
    """A small table on the edit page's Stats tab. This is raw HTML, so escape anything you include."""
    stats = STATS.get(watch.get('uuid'))
    if not stats:
        return '<p class="cdio-example-check-stats">No checks timed since the last restart.</p>'
    rows = [
        ('Checks timed since restart', stats['count']),
        ('Last check took', f"{stats['duration']:.2f}s"),
        ('Last check', 'OK' if stats['ok'] else f"Failed: {stats['error']}"),
    ]
    body = ''.join(f'<tr><td>{escape(label)}</td><td>{escape(value)}</td></tr>' for label, value in rows)
    return f'<table class="pure-table cdio-example-check-stats"><tbody>{body}</tbody></table>'


@hookimpl
def plugin_static_path():
    """Files in here are served at /static/plugin/<filename>."""
    return os.path.join(os.path.dirname(__file__), 'static')


@hookimpl
def get_html_head_extras():
    """Added inside <head> on every page."""
    from flask import url_for
    css = url_for('static_content', group='plugin', filename='cdio_example_check_stats.css')
    return f'<link rel="stylesheet" href="{css}">'
