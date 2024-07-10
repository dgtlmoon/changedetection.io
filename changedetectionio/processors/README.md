# Change detection post-processors

The concept here is to be able to switch between different domain specific problems to solve.

- `text_json_diff` The traditional text and JSON comparison handler
- `restock_diff` Only cares about detecting if a product looks like it has some text that suggests that it's out of stock, otherwise assumes that it's in stock.

Some suggestions for the future

- `graphical` 

## Todo

- Make each processor return a extra list of sub-processed (so you could configure a single processor in different ways)
- move restock_diff to its own pip/github repo
