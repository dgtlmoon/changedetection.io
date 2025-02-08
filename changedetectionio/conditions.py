from json_logic import jsonLogic
from json_logic.builtins import BUILTINS
import re

# List of all supported JSON Logic operators
operator_choices = [
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
#    ("watch_uuid_unviewed_change", "Watch UUID had an unviewed change"),  #('if'? )
#    ("watch_uuid_not_unviewed_change", "Watch UUID NOT had an unviewed change") #('if'? )
#    ("watch_uuid_changed", "Watch UUID had unviewed change"),
#    ("watch_uuid_not_changed", "Watch UUID did NOT have unviewed change"),
#    ("!!", "Is Truthy"),
#    ("!", "Is Falsy"),
#    ("and", "All Conditions Must Be True"),
#    ("or", "At Least One Condition Must Be True"),
#    ("max", "Maximum of Values"),
#    ("min", "Minimum of Values"),
#    ("+", "Addition"),
#    ("-", "Subtraction"),
#    ("*", "Multiplication"),
#    ("/", "Division"),
#    ("%", "Modulo"),
#    ("log", "Logarithm"),
#    ("if", "Conditional If-Else")
]

# Fields available in the rules
field_choices = [
    ("extracted_number", "Extracted Number"),
    ("page_filtered_text", "Page text After Filters"),
    ("page_title", "Page Title"), # actual page title <title>
    ("watch_uuid", "Watch UUID"),
    ("watch_history_length", "History Length"),
    ("watch_history", "All Watch Text History"),
    ("watch_check_count", "Watch Check Count"),
    ("watch_uuid", "Other Watch by UUID"), # (Maybe this is 'if' ??)
    #("requests_get", "Web GET requests (https://..)")
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
