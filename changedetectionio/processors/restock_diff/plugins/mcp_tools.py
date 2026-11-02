"""
The restock_diff processor's MCP tools (register_mcp_tools hook, see pluggy_interface.py):

- restock_status: which product monitors are in stock and at what price, across all of them or one tag
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


def _describe(state):
    stock = {True: 'in stock', False: 'out of stock'}.get(state['in_stock'], 'stock not known yet')
    price = f", {state['price']} {state['currency'] or ''}".rstrip() if state['price'] is not None else ''
    return stock + price


def restock_status(ctx, args, watch):
    from changedetectionio.blueprint.mcp.tools import _resolve_tag
    datastore = ctx.datastore
    tag_uuid = _resolve_tag(datastore, args['tag']) if args.get('tag') else None
    watches = [w for w in datastore.data['watching'].values()
               if w.get('processor') == PROCESSOR and (not tag_uuid or tag_uuid in (w.get('tags') or []))]
    if watch is not None:
        watches = [watch]
    if args.get('in_stock') is not None:
        watches = [w for w in watches if _state(w)['in_stock'] is args['in_stock']]
    watches.sort(key=lambda w: (w.label or '').lower())

    items = []
    for w in watches[:STATUS_MAX]:
        rules, source = _rules(datastore, w)
        items.append({'uuid': w.get('uuid'), 'title': w.label, 'url': w.get('url'), **_state(w),
                      'last_checked': w.get('last_checked') or None, 'last_error': w.get('last_error') or None,
                      'rules': rules, 'rules_from': source})

    lines = [f"{len(watches)} product monitors (restock_diff)" + (f", showing {STATUS_MAX}" if len(watches) > STATUS_MAX else '')]
    for item in items:
        line = f"- {item['title']} | {_describe(item)} | uuid {item['uuid']}"
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
         'description': "Which product monitors (processor restock_diff) are in stock and at what price, with their "
                        "notification rules. Use it for 'what on my wishlist is back in stock?' or 'what's the "
                        "cheapest?'. All of them, one tag, or one monitor.",
         'input_schema': {'tag': {'type': 'string', 'description': 'Only monitors in this tag/group (name or uuid)'},
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
