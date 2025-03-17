import pluggy
from price_parser import Price
from loguru import logger

hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")


@hookimpl
def register_operators():
    def starts_with(_, text, prefix):
        return text.lower().strip().startswith(str(prefix).strip().lower())

    def ends_with(_, text, suffix):
        return text.lower().strip().endswith(str(suffix).strip().lower())

    return {
        "starts_with": starts_with,
        "ends_with": ends_with
    }

@hookimpl
def register_operator_choices():
    return [
        ("starts_with", "Text Starts With"),
        ("ends_with", "Text Ends With"),
    ]

@hookimpl
def register_field_choices():
    return [
        ("extracted_number", "Extracted number after 'Filters & Triggers'"),
#        ("meta_description", "Meta Description"),
#        ("meta_keywords", "Meta Keywords"),
        ("page_filtered_text", "Page text after 'Filters & Triggers'"),
        #("page_title", "Page <title>"), # actual page title <title>
    ]

@hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):

    res = {}
    if 'text' in ephemeral_data:
        res['page_filtered_text'] = ephemeral_data['text']

        # Better to not wrap this in try/except so that the UI can see any errors
        price = Price.fromstring(ephemeral_data.get('text'))
        if price and price.amount != None:
            # This is slightly misleading, it's extracting a PRICE not a Number..
            res['extracted_number'] = float(price.amount)
            logger.debug(f"Extracted number result: '{price}' - returning float({res['extracted_number']})")

    return res
