import pluggy
from loguru import logger

hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")

def levenshtein_ratio_recent_history(watch, incoming_text):
    try:
        from Levenshtein import ratio, distance
        k = list(watch.history.keys())
        if len(k) >= 2:
            a = watch.get_history_snapshot(timestamp=k[0])
            b = incoming_text
            distance = distance(a, b)
            return distance
    except Exception as e:
        logger.warning("Unable to calc similarity", e)

    return ''

@hookimpl
def register_operators():
    pass

@hookimpl
def register_operator_choices():
    pass


@hookimpl
def register_field_choices():
    return [
        ("levenshtein_ratio", "Levenshtein text difference distance/similarity"),
    ]

@hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):

    res = {}
    watch = application_datastruct['watching'].get(current_watch_uuid)
    if watch and 'text' in ephemeral_data:
        # This is slightly misleading, it's extracting a PRICE not a Number..
        res['levenshtein_ratio'] = levenshtein_ratio_recent_history(watch, ephemeral_data['text'])

    return res
