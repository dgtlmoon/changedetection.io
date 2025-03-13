import pluggy

hookimpl = pluggy.HookimplMarker("conditions")

@hookimpl
def register_operators():
    def starts_with(_, text, prefix):
        return text.lower().strip().startswith(prefix.lower())

    def ends_with(_, text, suffix):
        return text.lower().strip().endswith(suffix.lower())

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
        ("extracted_number", "Automatically extracted number"),
        ("meta_description", "Meta Description"),
        ("meta_keywords", "Meta Keywords"),
        ("page_filtered_text", "Page text after 'Filters & Triggers'"),
        ("page_title", "Page <title>"), # actual page title <title>
    ]
