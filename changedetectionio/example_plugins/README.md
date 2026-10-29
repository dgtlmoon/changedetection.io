# Example plugins

Small, working plugins to learn from or copy. Each one is its own installable package, nothing here is
active until you install it.

To install one, run `pip install .` from its directory, in the same Python environment that runs
changedetection.io, then restart changedetection.io. Plugins are picked up through the `changedetectionio`
entry point in their `pyproject.toml`. They need plugin API 0.2.0 or newer
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

## Writing your own

Copy an example's directory, then rename the package directory and its `name` / entry point in
`pyproject.toml`. For a processor, also change `PROCESSOR_NAME` and the two schema names in `api.yaml`.
Every hook and its arguments are documented on `ChangeDetectionSpec` in
[`pluggy_interface.py`](../pluggy_interface.py).

In Docker, add your published package to the `EXTRA_PACKAGES` environment variable instead of
running `pip install` yourself.
