"""Stream a metadata report without reading watch snapshots or histories."""

import csv
from io import StringIO

from flask import Response


def _spreadsheet_value(value):
    # Page titles and errors are untrusted text. Quoting alone does not prevent
    # spreadsheet applications from evaluating cells as formulas.
    if isinstance(value, str) and (
        value.startswith(('\t', '\r', '\n')) or value.lstrip().startswith(('=', '+', '-', '@'))
    ):
        return "'" + value
    return value


def selected_watches_csv(datastore, uuids):
    def rows():
        yield '\ufeff'  # UTF-8 BOM lets spreadsheet applications recognize non-ASCII titles.
        buffer = StringIO(newline='')
        writer = csv.writer(buffer)

        def encode(values):
            buffer.seek(0)
            buffer.truncate()
            writer.writerow([_spreadsheet_value(value) for value in values])
            return buffer.getvalue()

        yield encode(('uuid', 'url', 'title', 'last_error', 'last_checked', 'in_stock', 'price', 'currency'))
        for uuid in uuids:
            watch = datastore.data['watching'].get(uuid)
            # A selection can contain a watch deleted in another tab while the
            # export was being requested. Never fall back to exporting all watches.
            if watch is None:
                continue
            restock = watch.get('restock') or {}
            yield encode((
                uuid,
                watch.get('url', ''),
                watch.get('title') or watch.get('page_title') or '',
                watch.get('last_error') or '',
                watch.get('last_checked') or '',
                restock.get('in_stock'),
                restock.get('price'),
                restock.get('currency'),
            ))

    return Response(rows(), content_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="selected-watches.csv"',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })
