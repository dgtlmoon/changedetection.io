import pluggy
from loguru import logger

# Support both plugin systems
conditions_hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")
global_hookimpl = pluggy.HookimplMarker("changedetectionio")

def count_words_in_history(watch, incoming_text=None):
    """Count words in snapshot text"""
    try:
        if incoming_text is not None:
            # When called from add_data with incoming text
            return len(incoming_text.split())
        elif watch.history.keys():
            # When called from UI extras to count latest snapshot
            latest_key = list(watch.history.keys())[-1]
            latest_content = watch.get_history_snapshot(latest_key)
            return len(latest_content.split())
        return 0
    except Exception as e:
        logger.error(f"Error counting words: {str(e)}")
        return 0

# Implement condition plugin hooks
@conditions_hookimpl
def register_operators():
    # No custom operators needed
    return {}

@conditions_hookimpl
def register_operator_choices():
    # No custom operator choices needed
    return []

@conditions_hookimpl
def register_field_choices():
    # Add a field that will be available in conditions
    return [
        ("word_count", "Word count of content"),
    ]

@conditions_hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):
    """Add word count data for conditions"""
    result = {}
    watch = application_datastruct['watching'].get(current_watch_uuid)
    
    if watch and 'text' in ephemeral_data:
        word_count = count_words_in_history(watch, ephemeral_data['text'])
        result['word_count'] = word_count
    
    return result

def _generate_stats_html(watch):
    """Generate the HTML content for the stats tab"""
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
        <p style="font-size: 80%;">Word count is a simple measure of content length, calculated by splitting text on whitespace.</p>
    </div>
    """
    return html

@conditions_hookimpl
def ui_edit_stats_extras(watch):
    """Add word count stats to the UI through conditions plugin system"""
    return _generate_stats_html(watch)

@global_hookimpl
def ui_edit_stats_extras(watch):
    """Add word count stats to the UI using the global plugin system"""
    return _generate_stats_html(watch)