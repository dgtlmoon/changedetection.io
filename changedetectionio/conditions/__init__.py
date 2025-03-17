from flask import Blueprint, request, jsonify, Response
from flask_login import current_user
from json_logic.builtins import BUILTINS

from .exceptions import EmptyConditionRuleRowNotUsable
from .pluggy_interface import plugin_manager  # Import the pluggy plugin manager
from . import default_plugin

import re
import json

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
#    ("changed > minutes", "Changed more than X minutes ago"),
]

# Fields available in the rules
field_choices = [
    (None, "Choose one"),
]

# The data we will feed the JSON Rules to see if it passes the test/conditions or not
EXECUTE_DATA = {}

# ✅ Custom function for case-insensitive regex matching
def contains_regex(_, text, pattern):
    """Returns True if `text` contains `pattern` (case-insensitive regex match)."""
    return bool(re.search(pattern, text, re.IGNORECASE))

# ✅ Custom function for NOT matching case-insensitive regex
def not_contains_regex(_, text, pattern):
    """Returns True if `text` does NOT contain `pattern` (case-insensitive regex match)."""
    return not bool(re.search(pattern, text, re.IGNORECASE))


# Define the extended operations dictionary
CUSTOM_OPERATIONS = {
    **BUILTINS,  # Include all standard operators
    "contains_regex": contains_regex,
    "!contains_regex": not_contains_regex
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
    
    ruleset_settings = application_datastruct['watching'].get(current_watch_uuid)

    if ruleset_settings.get("conditions"):
        logic_operator = "and" if ruleset_settings.get("conditions_match_logic", "ALL") == "ALL" else "or"
        complete_rules = filter_complete_rules(ruleset_settings['conditions'])
        if complete_rules:
            # Give all plugins a chance to update the data dict again (that we will test the conditions against)
            for plugin in plugin_manager.get_plugins():
                new_execute_data = plugin.add_data(current_watch_uuid=current_watch_uuid,
                                                   application_datastruct=application_datastruct,
                                                   ephemeral_data=ephemeral_data)

                if new_execute_data and isinstance(new_execute_data, dict):
                    EXECUTE_DATA.update(new_execute_data)

                ruleset = convert_to_jsonlogic(logic_operator=logic_operator, rule_dict=complete_rules)

                if not jsonLogic(logic=ruleset, data=EXECUTE_DATA):
                    result = False

    return result

# Flask Blueprint Definition
def construct_blueprint(datastore):
    from changedetectionio.flask_app import login_optionally_required
    
    conditions_blueprint = Blueprint('conditions', __name__, template_folder="templates")
    
    @conditions_blueprint.route("/<string:watch_uuid>/verify-condition-single-rule", methods=['POST'])
    @login_optionally_required
    def verify_condition_single_rule(watch_uuid):
        """Verify a single condition rule against the current snapshot"""
        
        # Get the watch data
        watch = datastore.data['watching'].get(watch_uuid)
        if not watch:
            return jsonify({'status': 'error', 'message': 'Watch not found'}), 404
        
        # Get the rule data from the request
        rule_data = request.json
        if not rule_data:
            return jsonify({'status': 'error', 'message': 'No rule data provided'}), 400
        
        # Create ephemeral data with the current snapshot
        ephemeral_data = {}
        
        # Get the current snapshot if available
        if watch.history_n and watch.get_last_fetched_text_before_filters():
            ephemeral_data['text'] = watch.get_last_fetched_text_before_filters()
        else:
            return jsonify({
                'status': 'error', 
                'message': 'No snapshot available for verification. Please fetch content first.'
            }), 400
        
        # Test the rule
        result = False
        try:
            # Create a temporary structure with just this rule
            temp_watch_data = {
                "conditions": [rule_data],
                "conditions_match_logic": "ALL"  # Single rule, so use ALL
            }
            
            # Create a temporary application data structure
            temp_app_data = {
                'watching': {
                    watch_uuid: temp_watch_data
                }
            }
            
            # Execute the rule against the current snapshot
            result = execute_ruleset_against_all_plugins(
                current_watch_uuid=watch_uuid,
                application_datastruct=temp_app_data,
                ephemeral_data=ephemeral_data
            )
            
            return jsonify({
                'status': 'success',
                'result': result,
                'message': 'Condition passes' if result else 'Condition does not pass'
            })
            
        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'Error verifying condition: {str(e)}'
            }), 500
    
    return conditions_blueprint

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

