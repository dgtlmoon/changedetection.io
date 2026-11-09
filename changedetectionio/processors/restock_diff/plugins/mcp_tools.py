"""
The restock_diff processor's MCP tools (register_mcp_tools hook, see pluggy_interface.py):

- restock_status: which product monitors are in stock and at what price, with their price history, across all
  of them, one tag or a name search
- restock_set_rules: when a product monitor notifies, back in stock only, and price limits

Core (blueprint/mcp/tools.py) checks the arguments, resolves the `watch` argument and refuses monitors that
aren't restock_diff, so these only do the restock part.
"""
from changedetectionio.plugin_api import hookimpl

PROCESSOR = 'restock_diff'
STATUS_MAX = 200

# The same settings and limits as the REST API's processor_config_restock_diff (../api.yaml), which validates
# REST requests itself; the MCP tool's schema does it here
RULES_SCHEMA = {
    'in_stock_processing': {
        'type': 'string', 'enum': ['in_stock_only', 'all_changes', 'off'],
        'description': "'in_stock_only' notifies when it comes back in stock, 'all_changes' on any stock change, "
                       "'off' ignores stock"},
    'follow_price_changes': {'type': 'boolean', 'description': 'Notify on price changes (within the limits below)'},
    'price_change_min': {'type': ['number', 'null'], 'minimum': 0,
                         'description': 'Notify when the price drops below this, null to remove the limit'},
    'price_change_max': {'type': ['number', 'null'], 'minimum': 0,
                         'description': 'Notify when the price rises above this, null to remove the limit'},
    'price_change_threshold_percent': {'type': ['number', 'null'], 'minimum': 0, 'maximum': 100,
                                       'description': 'Only price changes bigger than this %, null for any change'},
}


def _rules(datastore, watch):
    from changedetectionio.processors import get_resolved_processor_config
    return get_resolved_processor_config(datastore, watch)


def _state(watch):
    restock = watch.get('restock') or {}
    return {'in_stock': restock.get('in_stock'), 'price': restock.get('price'), 'currency': restock.get('currency')}


def _price_history(watch):
    """Lowest/highest/median price, low/typical/high now, the last price change and since when it's at this price,
    from the snapshots (difference.py's series and summary, the same numbers as the price graph). None without prices."""
    from changedetectionio.blueprint.mcp.tools import _iso
    from changedetectionio.processors.restock_diff.difference import _build_series, compute_price_summary
    series = [p for p in _build_series(watch) if p['price'] is not None]
    summary = compute_price_summary(series)
    if not summary:
        return None
    current = series[-1]['price']
    # Walk back over the run at the current price, the snapshot before it is the last change
    i = len(series) - 1
    while i > 0 and series[i - 1]['price'] == current:
        i -= 1
    history = {k: summary[k] for k in ('min', 'max', 'median', 'status', 'all_time_low')}
    history['snapshots'] = summary['count']
    history['since'] = _iso(series[i]['timestamp'])
    if i > 0:
        history['last_change'] = {'from': series[i - 1]['price'], 'to': current, 'date': _iso(series[i]['timestamp'])}
    return history


def _describe_history(h):
    if not h:
        return ''
    text = f" | {h['status']} for it (low {h['min']}, median {h['median']}, high {h['max']})"
    if h.get('last_change'):
        c = h['last_change']
        text += f" | was {c['from']} until {c['date'][:10]}"
    else:
        text += f" | unchanged since {h['since'][:10]}"
    return text


def _describe(state):
    stock = {True: 'in stock', False: 'out of stock'}.get(state['in_stock'], 'stock not known yet')
    price = f", {state['price']} {state['currency'] or ''}".rstrip() if state['price'] is not None else ''
    return stock + price


def restock_status(ctx, args, watch):
    import time
    from changedetectionio.blueprint.mcp.tools import CHANGES_TIME_BUDGET, _iso, _resolve_tag
    datastore = ctx.datastore
    tag_uuid = _resolve_tag(ctx, args['tag']) if args.get('tag') else None
    # ctx.watches(): only the monitors this access token may see
    watches = [w for w in ctx.watches()
               if w.get('processor') == PROCESSOR and (not tag_uuid or tag_uuid in (w.get('tags') or []))]
    if watch is not None:
        watches = [watch]
    search = (args.get('search') or '').strip().lower()
    if search:
        watches = [w for w in watches if search in (w.label or '').lower() or search in (w.get('url') or '').lower()]
    if args.get('in_stock') is not None:
        watches = [w for w in watches if _state(w)['in_stock'] is args['in_stock']]
    watches.sort(key=lambda w: (w.label or '').lower())

    items, deadline, no_history = [], time.monotonic() + CHANGES_TIME_BUDGET, 0
    for w in watches[:STATUS_MAX]:
        rules, source = _rules(datastore, w)
        item = {'uuid': w.get('uuid'), 'title': w.label, 'url': w.get('url'), **_state(w),
                'last_checked': _iso(w['last_checked']) if w.get('last_checked') else None,
                'last_error': w.get('last_error') or None, 'rules': rules, 'rules_from': source}
        # Reading every snapshot is cheap for these (a line each), but many monitors with long histories are
        # bounded by the same time budget as get_changes
        if time.monotonic() < deadline:
            time.sleep(0)
            item['price_history'] = _price_history(w)
        else:
            no_history += 1
        items.append(item)

    lines = [f"{len(watches)} product monitors (restock_diff)" + (f", showing {STATUS_MAX}" if len(watches) > STATUS_MAX else '')]
    if no_history:
        lines.append(f"Price history left out for {no_history} of them (time limit), narrow it down with 'search' or 'tag'.")
    for item in items:
        line = f"- {item['title']} | {_describe(item)}{_describe_history(item.get('price_history'))} | uuid {item['uuid']}"
        if item['last_error']:
            line += f" | last check failed: {item['last_error']}"
        lines.append(line)
    if not items:
        lines.append("None match. Add one with create_watch and processor 'restock_diff'.")
    return '\n'.join(lines), {'monitors': items, 'total': len(watches)}


def restock_set_rules(ctx, args, watch):
    from changedetectionio.api.operations import update_watch
    from changedetectionio.blueprint.mcp.tools import ToolError, _api_call
    changes = {k: args[k] for k in RULES_SCHEMA if k in args}
    if not changes:
        raise ToolError("Nothing to change, give one of: " + ', '.join(RULES_SCHEMA))
    rules, source = _rules(ctx.datastore, watch)
    if source.startswith('tag:'):
        # The processor would keep using the tag's rules, saving the monitor's own would silently do nothing
        tag = ctx.datastore.data['settings']['application']['tags'].get(source[4:], {})
        raise ToolError(f"'{watch.label}' takes its restock rules from the tag '{tag.get('title')}', which overrides "
                        f"its own. Change them on that tag in the changedetection.io UI.")
    low, high = changes.get('price_change_min', rules.get('price_change_min')), \
        changes.get('price_change_max', rules.get('price_change_max'))
    if low is not None and high is not None and low > high:
        raise ToolError(f"price_change_min ({low}) can't be above price_change_max ({high})")

    # The saved settings are replaced as a whole, so merge into the current ones
    merged = {**rules, **changes}
    _api_call(update_watch, ctx.datastore, watch.get('uuid'), {f'processor_config_{PROCESSOR}': merged})
    saved, _ = _rules(ctx.datastore, watch)
    summary = ', '.join(f"{k}={saved.get(k)}" for k in RULES_SCHEMA if k in saved)
    return f"Updated the restock rules of {watch.label}: {summary}", {'uuid': watch.get('uuid'), 'rules': saved}


@hookimpl
def register_mcp_tools():
    from changedetectionio.blueprint.mcp.tools import WATCH_ARGUMENT
    return [
        {'name': 'restock_status', 'title': 'Stock and prices', 'kind': 'read',
         'description': "Which product monitors are in stock and at what price, with their price history (lowest, "
                        "median, highest, whether now is low/typical/high, the last price change and since when) and "
                        "restock alert rules. Use it for 'what on my wishlist is back in stock?' or 'is anything "
                        "cheap now?'. No arguments for all product monitors, or narrow it to one tag, a name search "
                        "or one monitor, and in_stock=true/false. Sorted by name. Only product (restock) monitors; "
                        "for other monitors' settings or latest change, use get_watch.",
         'input_schema': {'tag': {'type': 'string', 'description': 'Only monitors in this tag/group (name or uuid)'},
                          'search': {'type': 'string', 'description': 'Only monitors whose title or URL contains this'},
                          'watch': WATCH_ARGUMENT,
                          'in_stock': {'type': 'boolean', 'description': 'Only the ones in stock (true) or out of stock (false)'}},
         'processor': PROCESSOR, 'handler': restock_status},
        {'name': 'restock_set_rules', 'title': 'Set restock alerts', 'kind': 'write',
         'description': "When a product monitor (processor restock_diff) notifies: when it's back in stock, when "
                        "the price drops below or rises above a limit, or only on bigger price changes. Only the "
                        "rules given are changed. Create the monitor first with create_watch and processor "
                        "'restock_diff'.",
         'input_schema': {'watch': WATCH_ARGUMENT, **RULES_SCHEMA}, 'required': ['watch'],
         'processor': PROCESSOR, 'handler': restock_set_rules},
    ]
