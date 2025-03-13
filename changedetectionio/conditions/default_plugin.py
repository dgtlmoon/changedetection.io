import pluggy
from price_parser import Price
from loguru import logger

hookimpl = pluggy.HookimplMarker("changedetectionio_conditions")


@hookimpl
def register_operators():
    def starts_with(_, text, prefix):
        return text.lower().strip().startswith(prefix.lower())

    def ends_with(_, text, suffix):
        return text.lower().strip().endswith(suffix.lower())

    def extracted_number(_, text, suffix):
        return 1

    return {
        "starts_with": starts_with,
        "ends_with": ends_with,
        "extracted_number": extracted_number
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
        ("page_title", "Page <title>"), # actual page title <title>
    ]

@hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):


    res = {}
    if 'text' in ephemeral_data:
        res['page_text'] = ephemeral_data['text']

        # Better to not wrap this in try/except so that the UI can see any errors
        price = Price.fromstring(ephemeral_data.get('text'))
        if price:
            res['extracted_number'] = float(price.amount)
        logger.debug(f"Extracted price result: '{price}' - returning float({res['extracted_number']})")


    return res
