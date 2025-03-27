# Flask Blueprint Definition
import json

from flask import Blueprint

from changedetectionio.conditions import execute_ruleset_against_all_plugins


def construct_blueprint(datastore):
    from changedetectionio.flask_app import login_optionally_required

    conditions_blueprint = Blueprint('conditions', __name__, template_folder="templates")

    @conditions_blueprint.route("/<string:watch_uuid>/verify-condition-single-rule", methods=['POST'])
    @login_optionally_required
    def verify_condition_single_rule(watch_uuid):
        """Verify a single condition rule against the current snapshot"""
        from changedetectionio.processors.text_json_diff import prepare_filter_prevew
        from flask import request, jsonify
        from copy import deepcopy

        ephemeral_data = {}

        # Get the watch data
        watch = datastore.data['watching'].get(watch_uuid)
        if not watch:
            return jsonify({'status': 'error', 'message': 'Watch not found'}), 404

        # First use prepare_filter_prevew to process the form data
        # This will return text_after_filter which is after all current form settings are applied
        # Create ephemeral data with the text from the current snapshot

        try:
            # Call prepare_filter_prevew to get a processed version of the content with current form settings
            # We'll ignore the returned response and just use the datastore which is modified by the function

            # this should apply all filters etc so then we can run the CONDITIONS against the final output text
            result = prepare_filter_prevew(datastore=datastore,
                                           form_data=request.form,
                                           watch_uuid=watch_uuid)

            ephemeral_data['text'] = result.get('after_filter', '')
            # Create a temporary watch data structure with this single rule
            tmp_watch_data = deepcopy(datastore.data['watching'].get(watch_uuid))

            # Override the conditions in the temporary watch
            rule_json = request.args.get("rule")
            rule = json.loads(rule_json) if rule_json else None

            # Should be key/value of field, operator, value
            tmp_watch_data['conditions'] = [rule]
            tmp_watch_data['conditions_match_logic'] = "ALL"  # Single rule, so use ALL

            # Create a temporary application data structure for the rule check
            temp_app_data = {
                'watching': {
                    watch_uuid: tmp_watch_data
                }
            }

            # Execute the rule against the current snapshot with form data
            result = execute_ruleset_against_all_plugins(
                current_watch_uuid=watch_uuid,
                application_datastruct=temp_app_data,
                ephemeral_data=ephemeral_data
            )

            return jsonify({
                'status': 'success',
                'result': result.get('result'),
                'data': result.get('executed_data'),
                'message': 'Condition passes' if result else 'Condition does not pass'
            })

        except Exception as e:
            return jsonify({
                'status': 'error',
                'message': f'Error verifying condition: {str(e)}'
            }), 500

    return conditions_blueprint