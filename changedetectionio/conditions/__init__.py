from json_logic.builtins import BUILTINS

from .exceptions import EmptyConditionRuleRowNotUsable
from .pluggy_interface import plugin_manager  # Import the pluggy plugin manager
from . import default_plugin
from loguru import logger
# List of all supported JSON Logic operators
operator_choices = [
    (None, "Choose one - Operator"),
    (">", "Greater Than"),
    ("<", "Less Than"),
    (">=", "Greater Than or Equal To"),
    ("<=", "Less Than or Equal To"),
    ("==", "Equals"),
    ("!=", "Not Equals"),
    ("in", "Contains"),
]

# Fields available in the rules
field_choices = [
    (None, "Choose one - Field"),
]

# The data we will feed the JSON Rules to see if it passes the test/conditions or not
EXECUTE_DATA = {}


# Define the extended operations dictionary
CUSTOM_OPERATIONS = {
    **BUILTINS,  # Include all standard operators
}

def filter_complete_rules(ruleset):
    rules = [
        rule for rule in ruleset
        if all(value not in ("", False, "None", None) for value in [rule["operator"], rule["field"], rule["value"]])
    ]
    return rules

def convert_to_jsonlogic(logic_operator: str, rule_dict: list):
    """
    Convert a structured rule dict into a JSON Logic rule.

    :param rule_dict: Dictionary containing conditions.
    :return: JSON Logic rule as a dictionary.
    """


    json_logic_conditions = []

    for condition in rule_dict:
        operator = condition["operator"]
        field = condition["field"]
        value = condition["value"]

        if not operator or operator == 'None' or not value or not field:
            raise EmptyConditionRuleRowNotUsable()

        # Convert value to int/float if possible
        try:
            if isinstance(value, str) and "." in value and str != "None":
                value = float(value)
            else:
                value = int(value)
        except (ValueError, TypeError):
            pass  # Keep as a string if conversion fails

        # Handle different JSON Logic operators properly
        if operator == "in":
            json_logic_conditions.append({"in": [value, {"var": field}]})  # value first
        elif operator in ("!", "!!", "-"):
            json_logic_conditions.append({operator: [{"var": field}]})  # Unary operators
        elif operator in ("min", "max", "cat"):
            json_logic_conditions.append({operator: value})  # Multi-argument operators
        else:
            json_logic_conditions.append({operator: [{"var": field}, value]})  # Standard binary operators

    return {logic_operator: json_logic_conditions} if len(json_logic_conditions) > 1 else json_logic_conditions[0]


def execute_ruleset_against_all_plugins(current_watch_uuid: str, application_datastruct, ephemeral_data={} ):
    """
    Build our data and options by calling our plugins then pass it to jsonlogic and see if the conditions pass

    :param ruleset: JSON Logic rule dictionary.
    :param extracted_data: Dictionary containing the facts.   <-- maybe the app struct+uuid
    :return: Dictionary of plugin results.
    """
    from json_logic import jsonLogic

    EXECUTE_DATA = {}
    result = True
    
    watch = application_datastruct['watching'].get(current_watch_uuid)

    if watch and watch.get("conditions"):
        logic_operator = "and" if watch.get("conditions_match_logic", "ALL") == "ALL" else "or"
        complete_rules = filter_complete_rules(watch['conditions'])
        if complete_rules:
            # Give all plugins a chance to update the data dict again (that we will test the conditions against)
            for plugin in plugin_manager.get_plugins():
                try:
                    import concurrent.futures
                    import time
                    
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            plugin.add_data,
                            current_watch_uuid=current_watch_uuid,
                            application_datastruct=application_datastruct,
                            ephemeral_data=ephemeral_data
                        )
                        logger.debug(f"Trying plugin {plugin}....")

                        # Set a timeout of 10 seconds
                        try:
                            new_execute_data = future.result(timeout=10)
                            if new_execute_data and isinstance(new_execute_data, dict):
                                EXECUTE_DATA.update(new_execute_data)

                        except concurrent.futures.TimeoutError:
                            # The plugin took too long, abort processing for this watch
                            raise Exception(f"Plugin {plugin.__class__.__name__} took more than 10 seconds to run.")
                except Exception as e:
                    # Log the error but continue with the next plugin
                    import logging
                    logging.error(f"Error executing plugin {plugin.__class__.__name__}: {str(e)}")
                    continue

            # Create the ruleset
            ruleset = convert_to_jsonlogic(logic_operator=logic_operator, rule_dict=complete_rules)
            
            # Pass the custom operations dictionary to jsonLogic
            if not jsonLogic(logic=ruleset, data=EXECUTE_DATA, operations=CUSTOM_OPERATIONS):
                result = False

    return {'executed_data': EXECUTE_DATA, 'result': result}

# Load plugins dynamically
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

def collect_ui_edit_stats_extras(watch):
    """Collect and combine HTML content from all plugins that implement ui_edit_stats_extras"""
    extras_content = []
    
    for plugin in plugin_manager.get_plugins():
        try:
            content = plugin.ui_edit_stats_extras(watch=watch)
            if content:
                extras_content.append(content)
        except Exception as e:
            # Skip plugins that don't implement the hook or have errors
            pass
            
    return "\n".join(extras_content) if extras_content else ""

