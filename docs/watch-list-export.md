# Export selected watches

Select watches in the watch list and click **Download CSV** in the bulk-action
bar. The download includes the selected watches across pages, using the existing
selection controls. Filtering does not automatically select every matching watch:
use the watch list's select-all-matching control when that is what you want.

The first line of the UTF-8 CSV is a note in column A, for example
`All dates are in timezone Europe/Prague`. The column names are on the second
line: `url`, `title`, `last_error`, `last_checked`, `in_stock`, `price`,
`currency` and `uuid`. Scripts reading the file should skip the first line.

`last_checked` is the local date and time in the instance's timezone (Settings >
Time & Date, otherwise `TZ`, otherwise UTC), written as `2026-11-20 16:06:23`.
It deliberately has no timezone suffix: LibreOffice Calc and Google Sheets only
turn a CSV value into a real, sortable date when there is none, which is why the
timezone is stated once on the first line. An unchecked watch has an empty value. Missing stock/price data is empty, while
out-of-stock and a zero price remain `False` and `0`. Titles fall back to the
detected page title when no custom title exists.

This is a report of current metadata, not a settings backup or history export.
Rows are streamed without loading snapshots or histories. Watches deleted after
selection are skipped. An entirely stale selection produces only the CSV header;
it never expands into all watches. Downloading does not clear the selection or
change watch state.

The export uses the same password protection as the watch list and requires a
CSRF-protected POST. Text that could be interpreted as a spreadsheet formula is
prefixed with an apostrophe. Consumers processing the CSV as raw text should be
aware of that prefix.
