import pluggy
from loguru import logger

# Support both plugin systems
conditions_hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")
global_hookimpl = pluggy.HookimplMarker("changedetectionio")

def levenshtein_ratio_recent_history(watch, incoming_text=None):
    try:
        from Levenshtein import ratio, distance
        k = list(watch.history.keys())
        if len(k) >= 2:
            # When called from ui_edit_stats_extras, we don't have incoming_text
            if incoming_text is None:
                a = watch.get_history_snapshot(timestamp=k[-2])  # Previous snapshot
                b = watch.get_history_snapshot(timestamp=k[-1])  # Latest snapshot
            else:
                a = watch.get_history_snapshot(timestamp=k[0])
                b = incoming_text
            
            distance_value = distance(a, b)
            ratio_value = ratio(a, b)
            return {
                'distance': distance_value,
                'ratio': ratio_value,
                'percent_similar': round(ratio_value * 100, 2)
            }
    except Exception as e:
        logger.warning(f"Unable to calc similarity: {str(e)}")

    return ''

@conditions_hookimpl
def register_operators():
    pass

@conditions_hookimpl
def register_operator_choices():
    pass


@conditions_hookimpl
def register_field_choices():
    return [
        ("levenshtein_ratio", "Levenshtein text difference distance/similarity"),
    ]

@conditions_hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):
    res = {}
    watch = application_datastruct['watching'].get(current_watch_uuid)
    if watch and 'text' in ephemeral_data:
        lev_data = levenshtein_ratio_recent_history(watch, ephemeral_data['text'])
        if isinstance(lev_data, dict):
            res['levenshtein_ratio'] = lev_data['distance']
            res['levenshtein_similarity'] = lev_data['percent_similar']
        else:
            res['levenshtein_ratio'] = lev_data

    return res

@conditions_hookimpl
def ui_edit_stats_extras(watch):
    """Add Levenshtein stats to the UI through conditions plugin system"""
    return _generate_stats_html(watch)
    
def _generate_stats_html(watch):
    """Generate the HTML for Levenshtein stats - shared by both plugin systems"""
    if len(watch.history.keys()) < 2:
        return "<p>Not enough history to calculate Levenshtein metrics</p>"
    
    try:
        lev_data = levenshtein_ratio_recent_history(watch)
        if not lev_data or not isinstance(lev_data, dict):
            return "<p>Unable to calculate Levenshtein metrics</p>"
            
        html = f"""
        <div class="levenshtein-stats">
            <h4>Levenshtein Text Similarity Details</h4>
            <table class="pure-table">
                <tbody>
                    <tr>
                        <td>Raw distance (edits needed)</td>
                        <td>{lev_data['distance']}</td>
                    </tr>
                    <tr>
                        <td>Similarity ratio</td>
                        <td>{lev_data['ratio']:.4f}</td>
                    </tr>
                    <tr>
                        <td>Percent similar</td>
                        <td>{lev_data['percent_similar']}%</td>
                    </tr>
                </tbody>
            </table>
            <p style="font-size: 80%;">Levenshtein metrics compare the last two snapshots, measuring how many character edits are needed to transform one into the other.</p>
        </div>
        """
        return html
    except Exception as e:
        logger.error(f"Error generating Levenshtein UI extras: {str(e)}")
        return "<p>Error calculating Levenshtein metrics</p>"
        
@global_hookimpl
def ui_edit_stats_extras(watch):
    """Add Levenshtein stats to the UI using the global plugin system"""
    return _generate_stats_html(watch)
