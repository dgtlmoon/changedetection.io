# Example plugins

Working examples to copy when writing your own changedetection.io plugin. They ship with the package
but are **not active**: nothing scans `example_plugins/`, a plugin only runs once it is registered.
The tests register them to check the plugin hooks keep working.

Like any plugin they import only from `changedetectionio.plugin_api`, everything else in the package is
internal and may change between releases. If you need something that isn't exported there, ask for it.

## `processor/wordcounter` - a processor plugin

Counts the words on a page, a change is detected when the count changes. It shows:

- `register_processor` - adds `word_counter` to the processor list (and the API `processor` field)
- `processor.py` - the check itself, returns the snapshot text and an `update_obj` for the watch
- `api.yaml` - `processor_config_word_counter` (settings, accepted on watch create/update) and
  `processor_state_word_counter` (read-only, what the last check found)
- `get_api_watch_processor_state` - publishes the word count as `processor_state_word_counter` on
  `GET /api/v1/watch/<uuid>` and in `GET /api/v1/watch`

### Making it your own package

1. Copy `processor/wordcounter/` into a new project, e.g. `my_cdio_processor/`, and rename
   `PROCESSOR_NAME` plus the two schema names in `api.yaml` to match.
2. Register it through the `changedetectionio` entry point in your `pyproject.toml`:

   ```toml
   [project.entry-points.changedetectionio]
   my_processor = "my_cdio_processor"
   ```

3. `pip install -e .` next to changedetection.io (or add it to `EXTRA_PACKAGES` in Docker) and restart.
