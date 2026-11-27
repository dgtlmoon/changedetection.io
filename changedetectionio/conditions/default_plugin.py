from loguru import logger
from flask_babel import lazy_gettext as _l

from changedetectionio.plugin_api import hookimpl


@hookimpl
def register_operators():
    def starts_with(_, text, prefix):
        return text.lower().strip().startswith(str(prefix).strip().lower())

    def ends_with(_, text, suffix):
        return text.lower().strip().endswith(str(suffix).strip().lower())

    def length_min(_, text, strlen):
        return len(text) >= int(strlen)

    def length_max(_, text, strlen):
        return len(text) <= int(strlen)

    def regex_found(text, pattern):
        """True when `pattern` is found in `text`, case-insensitive.

        Uses the 'regex' package so the search has a time limit: the text is the watched page and one that
        happens to (or is made to) backtrack badly against the pattern would otherwise hold the check forever.
        A search that runs out of time fails the check with a message, it is never taken as "not found".
        """
        # Imported here: only needed by watches that use a regex condition
        import regex as regex_lib
        from changedetectionio.jinja2_custom.plugins import regex as regex_plugin
        try:
            return bool(regex_lib.search(pattern, str(text), regex_lib.IGNORECASE, timeout=regex_plugin.REGEX_TIMEOUT_SECONDS))
        except TimeoutError:
            raise TimeoutError(
                f"A 'matches regex' condition took longer than {regex_plugin.REGEX_TIMEOUT_SECONDS} seconds, try a simpler RegEx"
            ) from None

    # Custom function for case-insensitive regex matching
    def contains_regex(_, text, pattern):
        """Returns True if `text` contains `pattern` (case-insensitive regex match)."""
        return regex_found(text, pattern)

    # Custom function for NOT matching case-insensitive regex
    def not_contains_regex(_, text, pattern):
        """Returns True if `text` does NOT contain `pattern` (case-insensitive regex match)."""
        return not regex_found(text, pattern)

    def not_contains(_, text, pattern):
        return not pattern in text

    return {
        "!in": not_contains,
        "!contains_regex": not_contains_regex,
        "contains_regex": contains_regex,
        "ends_with": ends_with,
        "length_max": length_max,
        "length_min": length_min,
        "starts_with": starts_with,
    }

@hookimpl
def register_operator_choices():
    return [
        ("!in", _l("Does NOT Contain")),
        ("starts_with", _l("Text Starts With")),
        ("ends_with", _l("Text Ends With")),
        ("length_min", _l("Length minimum")),
        ("length_max", _l("Length maximum")),
        ("contains_regex", _l("Text Matches Regex")),
        ("!contains_regex", _l("Text Does NOT Match Regex")),
    ]

@hookimpl
def register_field_choices():
    return [
        ("extracted_number", _l("Extracted number after 'Filters & Triggers'")),
#        ("meta_description", "Meta Description"),
#        ("meta_keywords", "Meta Keywords"),
        ("page_filtered_text", _l("Page text after 'Filters & Triggers'")),
        #("page_title", "Page <title>"), # actual page title <title>
    ]

@hookimpl
def add_data(current_watch_uuid, application_datastruct, ephemeral_data):

    from price_parser import Price
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
