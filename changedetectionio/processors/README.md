# Change detection post-processors

The concept here is to be able to switch between different domain specific problems to solve.

- `text_json_diff` The traditional text and JSON comparison handler
- `restock_diff` Only cares about detecting if a product looks like it has some text that suggests that it's out of stock, otherwise assumes that it's in stock.

Some suggestions for the future

- `graphical` 

## API schema extension (`api.yaml`)

A processor can extend the Watch/Tag API schema by placing an `api.yaml` alongside its `__init__.py`.
Define a `components.schemas.processor_config_<name>` entry and it will be merged into `WatchBase` at startup,
making `processor_config_<name>` a valid field on all watch create/update API calls.
The fully merged spec is served live at `/api/v1/full-spec`.

See `restock_diff/api.yaml` for a working example.

## Processor plugin hooks (`register_plugin_hooks`)

A processor can add its own plugin hooks: define `register_plugin_hooks(plugin_manager)` in its `__init__.py`
and it's called once at startup. Add your hookspecs there, and register built-in implementations with
`trylast=True` so any other plugin's implementation wins. `restock_diff` does this for its two price charts,
see `restock_diff/hookspecs.py` and `restock_diff/plugins/default_charts.py`.

## Todo

- Make each processor return a extra list of sub-processed (so you could configure a single processor in different ways)
- move restock_diff to its own pip/github repo
