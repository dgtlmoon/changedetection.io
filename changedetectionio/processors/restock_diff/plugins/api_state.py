"""Restock and price state of restock_diff watches in the REST API (processor_state_restock_diff)."""
from changedetectionio.plugin_api import hookimpl

# What the API exposes from watch['restock'], documented in ../api.yaml processor_state_restock_diff
API_STATE_FIELDS = ('in_stock', 'price', 'currency', 'last_price')


@hookimpl
def get_api_watch_processor_state(watch, processor_name, context):
    if processor_name != 'restock_diff':
        return None
    # In memory on the watch, so it's cheap enough for context='list' too
    restock = watch.get('restock') or {}
    return {k: restock.get(k) for k in API_STATE_FIELDS}
