from json_logic import jsonLogic
from json_logic.builtins import BUILTINS
from .pluggy_interface import plugin_manager  # Import the pluggy plugin manager
from . import default_plugin

import re

# List of all supported JSON Logic operators
operator_choices = [
    (None, "Choose one"),
    (">", "Greater Than"),
    ("<", "Less Than"),
    (">=", "Greater Than or Equal To"),
    ("<=", "Less Than or Equal To"),
    ("==", "Equals"),
    ("!=", "Not Equals"),
    ("in", "Contains"),
    ("!in", "Does Not Contain"),
    ("contains_regex", "Text Matches Regex"),
    ("!contains_regex", "Text Does NOT Match Regex"),
    ("changed > minutes", "Changed more than X minutes ago"),
]

# Fields available in the rules
field_choices = [
    (None, "Choose one"),

]


# ✅ Custom function for case-insensitive regex matching
def contains_regex(_, text, pattern):
    """Returns True if `text` contains `pattern` (case-insensitive regex match)."""
    return bool(re.search(pattern, text, re.IGNORECASE))

# ✅ Custom function for NOT matching case-insensitive regex
def not_contains_regex(_, text, pattern):
    """Returns True if `text` does NOT contain `pattern` (case-insensitive regex match)."""
    return not bool(re.search(pattern, text, re.IGNORECASE))


# ✅ Custom function to check if "watch_uuid" has changed
def watch_uuid_changed(_, previous_uuid, current_uuid):
    """Returns True if the watch UUID has changed."""
    return previous_uuid != current_uuid

# ✅ Custom function to check if "watch_uuid" has NOT changed
def watch_uuid_not_changed(_, previous_uuid, current_uuid):
    """Returns True if the watch UUID has NOT changed."""
    return previous_uuid == current_uuid

# Define the extended operations dictionary
CUSTOM_OPERATIONS = {
    **BUILTINS,  # Include all standard operators
    "watch_uuid_changed": watch_uuid_changed,
    "watch_uuid_not_changed": watch_uuid_not_changed,
    "contains_regex": contains_regex,
    "!contains_regex": not_contains_regex
}

# ✅ Load plugins dynamically
for plugin in plugin_manager.get_plugins():
    new_ops = plugin.register_operators()
    if isinstance(new_ops, dict):
        CUSTOM_OPERATIONS.update(new_ops)

    new_operator_choices = plugin.register_operator_choices()
    if isinstance(new_operator_choices, list):
        operator_choices.extend(new_operator_choices)

    new_field_choices = plugin.register_field_choices()
    if isinstance(new_field_choices, list):
        field_choices.extend(new_field_choices)

def run(ruleset, data):
    """
    Execute a JSON Logic rule against given data.

    :param ruleset: JSON Logic rule dictionary.
    :param data: Dictionary containing the facts.
    :return: Boolean result of rule evaluation.
    """


    try:
        return jsonLogic(ruleset, data, CUSTOM_OPERATIONS)
    except Exception as e:
        # raise some custom nice handler
        print(f"❌ Error evaluating JSON Logic: {e}")
        return False
