import pluggy
from loguru import logger

LEVENSHTEIN_MAX_LEN_FOR_EDIT_STATS=100000

# Support both plugin systems
conditions_hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")
global_hookimpl = pluggy.HookimplMarker("changedetectionio")

def levenshtein_ratio_recent_history(watch, incoming_text=None):
    try:
        from Levenshtein import ratio, distance
        k = list(watch.history.keys())
        a = None
        b = None

        # When called from ui_edit_stats_extras, we don't have incoming_text
        if incoming_text is None:
            a = watch.get_history_snapshot(timestamp=k[-1])  # Latest snapshot
            b = watch.get_history_snapshot(timestamp=k[-2])  # Previous snapshot

        # Needs atleast one snapshot
        elif len(k) >= 1: # Should be atleast one snapshot to compare against
            a = watch.get_history_snapshot(timestamp=k[-1]) # Latest saved snapshot
            b = incoming_text if incoming_text else k[-2]

        if a and b:
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
        ("levenshtein_ratio", "Levenshtein - Text similarity ratio"),
        ("levenshtein_distance", "Levenshtein - Text change distance"),
    ]

@conditions_hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):
    res = {}
    watch = application_datastruct['watching'].get(current_watch_uuid)
    # ephemeral_data['text'] will be the current text after filters, they may have edited filters but not saved them yet etc

    if watch and 'text' in ephemeral_data:
        lev_data = levenshtein_ratio_recent_history(watch, ephemeral_data.get('text',''))
        if isinstance(lev_data, dict):
            res['levenshtein_ratio'] = lev_data.get('ratio', 0)
            res['levenshtein_similarity'] = lev_data.get('percent_similar', 0)
            res['levenshtein_distance'] = lev_data.get('distance', 0)

    return res

@global_hookimpl
def ui_edit_stats_extras(watch):
    """Add Levenshtein stats to the UI using the global plugin system"""
    """Generate the HTML for Levenshtein stats - shared by both plugin systems"""
    if len(watch.history.keys()) < 2:
        return "<p>Not enough history to calculate Levenshtein metrics</p>"


    # Protection against the algorithm getting stuck on huge documents
    k = list(watch.history.keys())
    if any(
            len(watch.get_history_snapshot(timestamp=k[idx])) > LEVENSHTEIN_MAX_LEN_FOR_EDIT_STATS
            for idx in (-1, -2)
            if len(k) >= abs(idx)
    ):
        return "<p>Snapshot too large for edit statistics, skipping.</p>"

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
        
