from json_logic.builtins import BUILTINS
from flask_babel import lazy_gettext as _l

from .exceptions import EmptyConditionRuleRowNotUsable
from loguru import logger

# Seconds each add_data() implementation gets before it's skipped for this check
ADD_DATA_TIMEOUT = 10

# JSON Logic operators that are always available, plugins add more via register_operator_choices
BASE_OPERATOR_CHOICES = [
    (None, _l("Choose one - Operator")),
    (">", _l("Greater Than")),
    ("<", _l("Less Than")),
    (">=", _l("Greater Than or Equal To")),
    ("<=", _l("Less Than or Equal To")),
    ("==", _l("Equals")),
    ("!=", _l("Not Equals")),
    ("in", _l("Contains")),
]

# Fields come from plugins via register_field_choices
BASE_FIELD_CHOICES = [
    (None, _l("Choose one - Field")),
]


def _hook_results_in_registration_order(hook_caller):
    """pluggy calls implementations last-registered-first, so reverse that to keep the built-in
    choices (registered first) at the top of the lists."""
    return list(reversed(hook_caller()))


def get_custom_operations():
    """All JSON Logic operations: the json_logic builtins plus every plugin's register_operators()."""
    from changedetectionio.pluggy_interface import plugin_manager
    operations = {**BUILTINS}
    for new_ops in _hook_results_in_registration_order(plugin_manager.hook.register_operators):
        if isinstance(new_ops, dict):
            operations.update(new_ops)
    return operations


def get_operator_choices():
    """Operator <select> choices, called each time a conditions form is built (WTForms accepts a
    callable for choices), so plugins registered after startup show up too."""
    from changedetectionio.pluggy_interface import plugin_manager
    choices = list(BASE_OPERATOR_CHOICES)
    for new_choices in _hook_results_in_registration_order(plugin_manager.hook.register_operator_choices):
        if isinstance(new_choices, list):
            choices.extend(new_choices)
    return choices


def get_field_choices():
    """Field <select> choices, see get_operator_choices()."""
    from changedetectionio.pluggy_interface import plugin_manager
    choices = list(BASE_FIELD_CHOICES)
    for new_choices in _hook_results_in_registration_order(plugin_manager.hook.register_field_choices):
        if isinstance(new_choices, list):
            choices.extend(new_choices)
    return choices

def filter_complete_rules(ruleset):
    rules = [
        rule for rule in ruleset
        if all(
            rule.get(k) is not None
            and rule.get(k) is not False
            and rule.get(k) != ""
            and rule.get(k) != "None"
            for k in ("operator", "field", "value")
        )
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

        if (
            not operator
            or operator == 'None'
            or not field
            or value is None
            or value is False
            or value == ""
            or value == "None"
        ):
            raise EmptyConditionRuleRowNotUsable()

        # Convert value to int/float if possible
        try:
            if isinstance(value, str) and "." in value and value != "None":
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
            # Each implementation is called on its own so a slow one can be skipped without losing the others.
            import concurrent.futures
            from changedetectionio.pluggy_interface import plugin_manager
            add_data_kwargs = {
                'current_watch_uuid': current_watch_uuid,
                'application_datastruct': application_datastruct,
                'ephemeral_data': ephemeral_data,
            }
            # Registration order, so plugins installed later can refine facts from the built-ins
            for impl in plugin_manager.hook.add_data.get_hookimpls():
                # Like pluggy, only pass the arguments the implementation declares
                kwargs = {name: add_data_kwargs[name] for name in impl.argnames if name in add_data_kwargs}
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                try:
                    future = executor.submit(impl.function, **kwargs)
                    new_execute_data = future.result(timeout=ADD_DATA_TIMEOUT)
                    if new_execute_data and isinstance(new_execute_data, dict):
                        EXECUTE_DATA.update(new_execute_data)
                except concurrent.futures.TimeoutError:
                    logger.error(f"Conditions plugin '{impl.plugin_name}' took more than {ADD_DATA_TIMEOUT} seconds in add_data(), skipping it")
                except Exception as e:
                    # Implementations are already isolated by the plugin manager, this is a last resort
                    logger.error(f"Error executing conditions plugin '{impl.plugin_name}': {e}")
                finally:
                    # Don't wait for a timed-out implementation to finish
                    executor.shutdown(wait=False)

            # Create the ruleset
            ruleset = convert_to_jsonlogic(logic_operator=logic_operator, rule_dict=complete_rules)
            
            # Pass the custom operations dictionary to jsonLogic
            if not jsonLogic(logic=ruleset, data=EXECUTE_DATA, operations=get_custom_operations()):
                result = False

    return {'executed_data': EXECUTE_DATA, 'result': result}
