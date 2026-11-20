"""Stream a metadata report without reading watch snapshots or histories."""

import csv
from datetime import datetime, timezone
from io import StringIO
from zoneinfo import ZoneInfo

from flask import Response

from changedetectionio.time_handler import default_timezone_name

# First line of the report, in column A, followed by the timezone name
TIMEZONE_NOTE = 'All dates are in timezone'


def _report_timezone(datastore):
    """(tzinfo, name) of the instance's timezone: Settings > Time & Date, else $TZ, else UTC."""
    application = (datastore.data.get('settings') or {}).get('application') or {}
    name = default_timezone_name(application.get('scheduler_timezone_default'))
    try:
        return ZoneInfo(name), name
    except Exception:
        return timezone.utc, 'UTC'


def _checked_at(epoch, tz):
    """A Unix timestamp as "2026-11-20 16:06:23", local time in the report's timezone.

    Written without a timezone suffix on purpose: LibreOffice Calc and Google Sheets only turn a
    CSV value into a real, sortable date when it has none (with "+01:00", "Z" or "UTC" on it they
    keep it as text). Which timezone it is, is stated once, on the first line of the report.
    Never checked -> empty.
    """
    if not epoch:
        return ''
    return datetime.fromtimestamp(int(epoch), tz).strftime('%Y-%m-%d %H:%M:%S')


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

        tz, tz_name = _report_timezone(datastore)
        # Line 1, column A: which timezone the dates below are in. The column names are on line 2.
        yield encode((f'{TIMEZONE_NOTE} {tz_name}',))
        # uuid goes last: it is for machines, the columns a person reads come first
        yield encode(('url', 'title', 'last_error', 'last_checked', 'in_stock', 'price', 'currency', 'uuid'))
        for uuid in uuids:
            watch = datastore.data['watching'].get(uuid)
            # A selection can contain a watch deleted in another tab while the
            # export was being requested. Never fall back to exporting all watches.
            if watch is None:
                continue
            restock = watch.get('restock') or {}
            yield encode((
                watch.get('url', ''),
                watch.get('title') or watch.get('page_title') or '',
                watch.get('last_error') or '',
                _checked_at(watch.get('last_checked'), tz),
                restock.get('in_stock'),
                restock.get('price'),
                restock.get('currency'),
                uuid,
            ))

    return Response(rows(), content_type='text/csv; charset=utf-8', headers={
        'Content-Disposition': 'attachment; filename="selected-watches.csv"',
        'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff',
    })
