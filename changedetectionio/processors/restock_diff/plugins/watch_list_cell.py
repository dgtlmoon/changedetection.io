"""The stock and price of a restock watch in the watch list, kept current in the pages that have the list open.

The "Restock & Price" cell of a row is drawn with the list (templates/restock_diff/watch_list_cell.html). A new
watch has "No information" there until its first check, and a price that changes was only seen after a reload.
The same template is sent along with every update of the watch (the watch_list_row_html hook)."""
from changedetectionio.plugin_api import hookimpl


@hookimpl
def watch_list_row_html(watch):
    if watch.get('processor') != 'restock_diff':
        return None

    from flask import render_template
    return {'td.restock-and-price': render_template('restock_diff/watch_list_cell.html', watch=watch)}
