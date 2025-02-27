import pluggy

hookimpl = pluggy.HookimplMarker("conditions")

@hookimpl
def register_operators():
    def starts_with(_, text, prefix):
        return text.lower().startswith(prefix.lower())

    def ends_with(_, text, suffix):
        return text.lower().endswith(suffix.lower())

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
        ("meta_description", "Meta Description"),
        ("meta_keywords", "Meta Keywords"),
    ]