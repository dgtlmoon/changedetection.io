# Creating Plugins for changedetection.io

This document describes how to create plugins for changedetection.io. Plugins can be used to extend the functionality of the application in various ways.

## Plugin Types

### UI Stats Tab Plugins

These plugins can add content to the Stats tab in the Edit page. This is useful for adding custom statistics or visualizations about a watch.

#### Creating a UI Stats Tab Plugin

1. Create a Python file in a directory that will be loaded by the plugin system.

2. Use the `global_hookimpl` decorator to implement the `ui_edit_stats_extras` hook:

```python
import pluggy
from loguru import logger

global_hookimpl = pluggy.HookimplMarker("changedetectionio")

@global_hookimpl
def ui_edit_stats_extras(watch):
    """Add custom content to the stats tab"""
    # Calculate or retrieve your stats
    my_stat = calculate_something(watch)
    
    # Return HTML content as a string
    html = f"""
    <div class="my-plugin-stats">
        <h4>My Plugin Statistics</h4>
        <p>My statistic: {my_stat}</p>
    </div>
    """
    return html
```

3. The HTML you return will be included in the Stats tab.

## Plugin Loading

Plugins can be loaded from:

1. Built-in plugin directories in the codebase
2. External packages using setuptools entry points

To add a new plugin directory, modify the `plugin_dirs` dictionary in `pluggy_interface.py`.

## Example Plugin

Here's a simple example of a plugin that adds a word count statistic to the Stats tab:

```python
import pluggy
from loguru import logger

global_hookimpl = pluggy.HookimplMarker("changedetectionio")

def count_words_in_history(watch):
    """Count words in the latest snapshot"""
    try:
        if not watch.history.keys():
            return 0
            
        latest_key = list(watch.history.keys())[-1]
        latest_content = watch.get_history_snapshot(latest_key)
        return len(latest_content.split())
    except Exception as e:
        logger.error(f"Error counting words: {str(e)}")
        return 0

@global_hookimpl
def ui_edit_stats_extras(watch):
    """Add word count to the Stats tab"""
    word_count = count_words_in_history(watch)
    
    html = f"""
    <div class="word-count-stats">
        <h4>Content Analysis</h4>
        <table class="pure-table">
            <tbody>
                <tr>
                    <td>Word count (latest snapshot)</td>
                    <td>{word_count}</td>
                </tr>
            </tbody>
        </table>
    </div>
    """
    return html
```

## Testing Your Plugin

1. Place your plugin in one of the directories scanned by the plugin system
2. Restart changedetection.io
3. Go to the Edit page of a watch and check the Stats tab to see your content