# Example plugins

Small, working plugins to learn from or copy. Each one is its own installable package, nothing here is
active until you install it.

To install one, run `pip install .` from its directory, in the same Python environment that runs
changedetection.io, then restart changedetection.io. Plugins are picked up through the `changedetectionio`
entry point in their `pyproject.toml`. They need plugin API 0.3.0 or newer
(`changedetectionio.plugin_api.PLUGIN_API_VERSION`), the hello world example 0.5.0 or newer, the fallback fetcher 0.6.0 or newer,
the API key header 0.7.0 or newer.

Plugins import only from `changedetectionio.plugin_api`, everything else in the package is internal and
may change between releases. If you need something that isn't exported there, ask for it.

---

## Word counter - `processor/wordcounter`

A new processor, "Word counter (example plugin)", in the watch's processor list. It counts the words on
the page and reports a change when the count changes. The `min_word_length` setting skips short words.

**Hooks**
- `register_processor` - adds `word_counter` as a processor
- `get_api_watch_processor_state` - shows the count as `processor_state_word_counter` in the API
- `watch_list_extra_text` - "Found: 5 words" under the watch in the watch list

**Also shows** `processor.py` (the check itself) and `api.yaml` (documents `processor_config_word_counter`
and `processor_state_word_counter` in the API spec).

**Install**
```bash
cd changedetectionio/example_plugins/processor/wordcounter
pip install .
```

**Try it**
```bash
curl -X POST "http://localhost:5000/api/v1/watch" -H "x-api-key: YOUR_API_KEY" -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "processor": "word_counter", "processor_config_word_counter": {"min_word_length": 3}}'

# After the first check:
curl "http://localhost:5000/api/v1/watch/YOUR-UUID" -H "x-api-key: YOUR_API_KEY"
#   "processor_state_word_counter": {"word_count": 25}
```

---

## Example browser fetcher - `fetcher/example_browser_fetcher`

A new fetch method, "Example browser fetcher", that gets pages through its own API instead of fetching
them directly, for example a remote browser or rendering service.

**Hooks**
- `register_content_fetcher` - adds the `html_example_browser_fetcher` fetch method
- `plugin_settings_tab` - an "Example browser fetcher" tab in Settings for the API URL and key
- `fetcher_status_icon` - the icon next to watches using it in the watch list
- `plugin_static_path` - serves that icon

**Also shows** `fetcher.py`, a `Fetcher` subclass, reading its settings with `load_plugin_settings` and
returning a screenshot (random noise here, a real browser service would send its own).

**Install**
```bash
cd changedetectionio/example_plugins/fetcher/example_browser_fetcher
pip install .
```

**Try it:** in Settings > "Example browser fetcher", set the API URL with `{url}` where the page URL goes,
for example `https://api.example.com/fetch?url={url}`, and your key (sent as `X-Api-Key`). Then pick
"Example browser fetcher" as a watch's fetch method, or `"fetch_backend": "html_example_browser_fetcher"`
in the API.

---

## Fallback fetcher - `fetcher/fallback_fetcher`

A fetch method that gets pages from a scraping API, used for every check of a watch that picks it, or only
when a site blocks the normal fetch. With "Fall back on these status codes" set (e.g. `403, 429`), a check
that gets one of those is retried once, straight away, through the scraping API, so the watch doesn't show
an error. The watch is then "under control" of the plugin for a while ("Then keep using it for", 24h by
default): its checks go straight to the fallback, no more often than every 12h ("Meanwhile check no more
often than every", a minimum, so a watch already checked every 3 days stays at 3 days), and the watch list
says so. After that the normal fetch is tried again. "Only for these groups" limits it to some groups.
"Most successful calls in 24 hours" caps the cost: over it, checks that need the fallback fail with an error
saying when the next call is possible, without calling the API. A "Fetch stats" icon in the left sidebar
opens a page with the calls per hour, the limit, and the watches it has taken over.

Several fallback fetchers chain: each offers itself with its own "Priority" (lowest first, this one defaults
to 10), and when the first fails, or is over its daily limit and so doesn't offer itself, the next is tried
in the same check, up to `FETCH_FALLBACK_MAX_ATTEMPTS` retries (default 3). The watch shows an error only
when they all fail. Set `EXAMPLE_FETCHER_HELLOWORLD_TIME_BETWEEN_RECHECK_MINIMUM_SECONDS` to fix the minimum
recheck time for the whole install, the settings widget then shows it read-only.

**Hooks**
- `register_content_fetcher` - adds the `html_example_fallback_fetcher` fetch method
- `select_fetch_backend` - offers the fallback for one check, at its priority: before it (still under
  control) or as a retry after the normal fetch, or a fallback before it, failed (plugin API 0.6.0+)
- `recheck_seconds_override` - the longer recheck time while under control, the last word after the
  system, group and watch settings (plugin API 0.6.0+)
- `watch_list_extra_text` - "Blocked with HTTP 403, using the fallback fetcher, ..." under the watch
- `register_blueprints`, `register_sidebar_items` - the fetch stats page and its sidebar icon
- `plugin_settings_tab`, `fetcher_status_icon`, `plugin_static_path` - as in the example browser fetcher

**Also shows**
- the JSON contract it expects from the scraping API, at the top of `fetcher.py`. Most services take
  something close to it, adapt `_fetch()` to yours
- the same recheck time widget as the rest of the app in a settings form: `FormField(TimeBetweenCheckForm,
  render_kw={'class': 'time-check-widget'})`, read back with `time_between_check_to_seconds()`
- the plugin keeping its own state, `{datastore}/cdio_example_fallback_fetcher-state.json` (see `state.py`):
  the times of the successful calls in the last 24 hours, read once and kept in memory, written atomically

Which watches are under control is kept in memory only (`recheck_seconds_override` runs for every watch
every second, so it must not read files), so after a restart the first check tries the normal fetch again.

**Install**
```bash
cd changedetectionio/example_plugins/fetcher/fallback_fetcher
pip install .
```

**Try it:** in Settings > "Fallback fetcher", set the scraping API URL and key, and `403` under "Fall back
on these status codes". A watch whose site answers 403 is then fetched through the API on its next check.

---

## API key header - `request/api_key_header`

An API key header for each watch, set under "Show advanced options" in the edit page's Request tab and sent
with every check. The key is kept in the watch's data dir, not in the watch, so it isn't in the watch's JSON
or the API, and the page never shows it again (leave the field empty to keep it). The same three hooks are
what an OAuth 2.0 client credentials, HMAC request signing or rotating token plugin needs.

**Hooks** (plugin API 0.7.0+)
- `ui_edit_request_settings` - its WTForms form, nested into the edit form and validated with it, saved to
  `{watch data dir}/cdio_example_api_key_header.json`. `on_save` keeps the stored key when the field is empty
- `fetch_request_alter` - adds the header just before the fetch, unless the watch already sets it. Raising
  here fails the check with your message, rather than sending the request without the header
- `watch_settings_files` - "Clear history" keeps the JSON file

**Also shows** reading the settings back with `load_watch_plugin_settings(watch, plugin_id)`, and a template
under `templates/cdio_example_api_key_header/` that uses the core `_helpers.html` macros.

**Install**
```bash
cd changedetectionio/example_plugins/request/api_key_header
pip install .
```

**Try it:** add a watch of a page that echoes request headers (e.g. `https://httpbin.org/headers`), set a key
under Request > "Show advanced options", and look at the next snapshot.

---

## Check stats - `lifecycle/check_stats`

Times every check. Shows "Last check took 1.23s" under each watch in the watch list, and a small table on
the edit page's Stats tab. Stats are kept in memory, so they start again after a restart.

**Hooks**
- `update_handler_alter` - runs as a check starts, notes the time
- `update_finalize` - runs when the check is over (worked or not), records how long it took
- `watch_list_extra_text` - the note under the watch in the watch list
- `ui_edit_stats_extras` - the table on the edit page's Stats tab
- `get_html_head_extras` - links its CSS on every page
- `plugin_static_path` - serves that CSS

**Install**
```bash
cd changedetectionio/example_plugins/lifecycle/check_stats
pip install .
```

**Try it:** open the watch list after the next checks have run.

---

## Hello world - `ui/hello_world`

Its own page at `/hello-world`, shown inside the normal app layout (header, menu, styles), with a
"Hello world!" box and how many monitors you have, and a link to it in the left sidebar.

**Hooks**
- `register_blueprints` - mounts the plugin's Flask blueprint at `/hello-world`
- `register_sidebar_items` - the "Hello world" link in the left sidebar, highlighted while on the page

**Also shows** a template that extends `base.html`, kept under `templates/cdio_example_hello_world/` so
its path can't clash with a core template. The page needs the same login as the rest of the UI.

**Install**
```bash
cd changedetectionio/example_plugins/ui/hello_world
pip install .
```

**Try it:** open `http://localhost:5000/hello-world/`.

---

## Simple SVG chart - `restock/simple_svg_chart`

Replaces the price charts of restock & price watches (the one that rolls down from the History button in
the watch list, and the one on the history page) with a plain SVG line drawn on the server, no JavaScript.

**Hooks** (added by the `restock_diff` processor, see `processors/restock_diff/hookspecs.py`)
- `restock_diff_watchlist_overview_chart` - the chart under the watch in the watch list
- `restock_diff_watch_history_page_chart` - the chart on the history page

Each gets the price/stock history as `series` (plus `currency`, `summary`, `watch` if you want them)
and returns the chart's HTML. Implement just one to replace just that chart.

**Install**
```bash
cd changedetectionio/example_plugins/restock/simple_svg_chart
pip install .
```

**Try it:** open a restock & price watch's history page, or click its History button in the watch list.

---

## Writing your own

Copy an example's directory, then rename the package directory and its `name` / entry point in
`pyproject.toml`. Once installed, it's listed under Settings > Info with the first line of its docstring. For a processor, also change `PROCESSOR_NAME` and the two schema names in `api.yaml`.
Every hook and its arguments are documented on `ChangeDetectionSpec` in
[`pluggy_interface.py`](../pluggy_interface.py).

Plugins can add their own pages and endpoints with the `register_blueprints` hook: return a Flask
`Blueprint` (or `{'blueprint': bp, 'url_prefix': '/my-plugin'}`). Its routes need the same login as the
rest of the UI unless you return `'login_required': False` and secure them yourself.

In Docker, add your published package to the `EXTRA_PACKAGES` environment variable instead of
running `pip install` yourself.
