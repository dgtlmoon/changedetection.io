# Example plugins

Small, working plugins to learn from or copy. Each one is its own installable package, nothing here is
active until you install it.

To install one, run `pip install .` from its directory, in the same Python environment that runs
changedetection.io, then restart changedetection.io. Plugins are picked up through the `changedetectionio`
entry point in their `pyproject.toml`. They need plugin API 0.3.0 or newer
(`changedetectionio.plugin_api.PLUGIN_API_VERSION`).

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
