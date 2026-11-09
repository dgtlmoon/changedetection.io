"""Saves that a restock watch was viewed, as the trylast implementation of the hook in ../hookspecs.py,
so any other plugin implementing it wins."""
import time

from changedetectionio.plugin_api import hookimpl


@hookimpl(trylast=True)
def restock_diff_mark_watch_viewed(watch, datastore):
    datastore.set_last_viewed(watch.get('uuid'), time.time())
