import re
import threading

import requests
from flask import Blueprint, jsonify, request, render_template, flash, url_for, redirect
from flask_babel import gettext
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


# Slack webhook URL pattern: https://hooks.slack.com/services/T.../B.../...
SLACK_WEBHOOK_PATTERN = re.compile(
    r'^https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+$'
)


def construct_blueprint(datastore: ChangeDetectionStore):
    tags_blueprint = Blueprint('tags', __name__, template_folder="templates")

    @tags_blueprint.route("/list", methods=['GET'])
    @login_optionally_required
    def tags_overview_page():
        from .form import SingleTag
        add_form = SingleTag(request.form)

        sorted_tags = sorted(datastore.data['settings']['application'].get('tags').items(), key=lambda x: x[1]['title'])

        from collections import Counter

        tag_count = Counter(tag for watch in datastore.data['watching'].values() if watch.get('tags') for tag in watch['tags'])

        output = render_template("groups-overview.html",
                                 app_rss_token=datastore.data['settings']['application'].get('rss_access_token'),
                                 available_tags=sorted_tags,
                                 form=add_form,
                                 tag_count=tag_count,
                                 )

        return output

    @tags_blueprint.route("/add", methods=['POST'])
    @login_optionally_required
    def form_tag_add():
        from .form import SingleTag
        add_form = SingleTag(request.form)

        if not add_form.validate():
            for widget, l in add_form.errors.items():
                flash(','.join(l), 'error')
            return redirect(url_for('tags.tags_overview_page'))

        title = request.form.get('name').strip()

        if datastore.tag_exists_by_name(title):
            flash(gettext('The tag "{}" already exists').format(title), "error")
            return redirect(url_for('tags.tags_overview_page'))

        datastore.add_tag(title)
        flash(gettext("Tag added"))


        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/mute/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def mute(uuid):
        if datastore.data['settings']['application']['tags'].get(uuid):
            datastore.data['settings']['application']['tags'][uuid]['notification_muted'] = not datastore.data['settings']['application']['tags'][uuid]['notification_muted']
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/delete/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def delete(uuid):
        # Delete the tag from settings immediately
        if datastore.data['settings']['application']['tags'].get(uuid):
            del datastore.data['settings']['application']['tags'][uuid]

        # Remove tag from all watches in background thread to avoid blocking
        def remove_tag_background(tag_uuid):
            """Background thread to remove tag from watches - discarded after completion."""
            removed_count = 0
            try:
                for watch_uuid, watch in datastore.data['watching'].items():
                    if watch.get('tags') and tag_uuid in watch['tags']:
                        watch['tags'].remove(tag_uuid)
                        removed_count += 1
                logger.info(f"Background: Tag {tag_uuid} removed from {removed_count} watches")
            except Exception as e:
                logger.error(f"Error removing tag from watches: {e}")

        # Start daemon thread
        threading.Thread(target=remove_tag_background, args=(uuid,), daemon=True).start()

        flash(gettext("Tag deleted, removing from watches in background"))
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/unlink/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def unlink(uuid):
        # Unlink tag from all watches in background thread to avoid blocking
        def unlink_tag_background(tag_uuid):
            """Background thread to unlink tag from watches - discarded after completion."""
            unlinked_count = 0
            try:
                for watch_uuid, watch in datastore.data['watching'].items():
                    if watch.get('tags') and tag_uuid in watch['tags']:
                        watch['tags'].remove(tag_uuid)
                        unlinked_count += 1
                logger.info(f"Background: Tag {tag_uuid} unlinked from {unlinked_count} watches")
            except Exception as e:
                logger.error(f"Error unlinking tag from watches: {e}")

        # Start daemon thread
        threading.Thread(target=unlink_tag_background, args=(uuid,), daemon=True).start()

        flash(gettext("Unlinking tag from watches in background"))
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/delete_all", methods=['GET'])
    @login_optionally_required
    def delete_all():
        # Clear all tags from settings immediately
        datastore.data['settings']['application']['tags'] = {}

        # Clear tags from all watches in background thread to avoid blocking
        def clear_all_tags_background():
            """Background thread to clear tags from all watches - discarded after completion."""
            cleared_count = 0
            try:
                for watch_uuid, watch in datastore.data['watching'].items():
                    watch['tags'] = []
                    cleared_count += 1
                logger.info(f"Background: Cleared tags from {cleared_count} watches")
            except Exception as e:
                logger.error(f"Error clearing tags from watches: {e}")

        # Start daemon thread
        threading.Thread(target=clear_all_tags_background, daemon=True).start()

        flash(gettext("All tags deleted, clearing from watches in background"))
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/edit/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def form_tag_edit(uuid):
        from changedetectionio.blueprint.tags.form import group_restock_settings_form
        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)
        if not default:
            flash(gettext("Tag not found"), "error")
            return redirect(url_for('watchlist.index'))

        form = group_restock_settings_form(
                                       formdata=request.form if request.method == 'POST' else None,
                                       data=default,
                                       extra_notification_tokens=datastore.get_unique_notification_tokens_available(),
                                       default_system_settings = datastore.data['settings'],
                                       )

        template_args = {
            'data': default,
            'form': form,
            'watch': default,
            'extra_notification_token_placeholder_info': datastore.get_unique_notification_token_placeholders_available(),
        }

        included_content = {}
        if form.extra_form_content():
            # So that the extra panels can access _helpers.html etc, we set the environment to load from templates/
            # And then render the code from the module
            from jinja2 import Environment, FileSystemLoader
            import importlib.resources
            templates_dir = str(importlib.resources.files("changedetectionio").joinpath('templates'))
            env = Environment(loader=FileSystemLoader(templates_dir))
            template_str = """{% from '_helpers.html' import render_field, render_checkbox_field, render_button %}
        <script>        
            $(document).ready(function () {
                toggleOpacity('#overrides_watch', '#restock-fieldset-price-group', true);
            });
        </script>            
                <fieldset>
                    <div class="pure-control-group">
                        <fieldset class="pure-group">
                        {{ render_checkbox_field(form.overrides_watch) }}
                        <span class="pure-form-message-inline">Used for watches in "Restock & Price detection" mode</span>
                        </fieldset>
                </fieldset>
                """
            template_str += form.extra_form_content()
            template = env.from_string(template_str)
            included_content = template.render(**template_args)

        output = render_template("edit-tag.html",
                                 extra_form_content=included_content,
                                 extra_tab_content=form.extra_tab_content() if form.extra_tab_content() else None,
                                 settings_application=datastore.data['settings']['application'],
                                 **template_args
                                 )

        return output


    @tags_blueprint.route("/edit/<string:uuid>", methods=['POST'])
    @login_optionally_required
    def form_tag_edit_submit(uuid):
        from changedetectionio.blueprint.tags.form import group_restock_settings_form, SLACK_WEBHOOK_PATTERN
        if uuid == 'first':
            uuid = list(datastore.data['settings']['application']['tags'].keys()).pop()

        default = datastore.data['settings']['application']['tags'].get(uuid)

        form = group_restock_settings_form(formdata=request.form if request.method == 'POST' else None,
                               data=default,
                               extra_notification_tokens=datastore.get_unique_notification_tokens_available()
                               )

        # Validate Slack webhook URL if provided
        slack_webhook_url = request.form.get('slack_webhook_url', '').strip()
        if slack_webhook_url and not SLACK_WEBHOOK_PATTERN.match(slack_webhook_url):
            flash(gettext('Invalid Slack webhook URL format'), 'error')
            return redirect(url_for('tags.form_tag_edit', uuid=uuid))

        # Update tag data with form data
        datastore.data['settings']['application']['tags'][uuid].update(form.data)
        datastore.data['settings']['application']['tags'][uuid]['processor'] = 'restock_diff'

        # Handle Slack webhook fields explicitly (not in the base form)
        datastore.data['settings']['application']['tags'][uuid]['slack_webhook_url'] = slack_webhook_url or None
        datastore.data['settings']['application']['tags'][uuid]['slack_notification_muted'] = request.form.get('slack_notification_muted') == 'y'

        # Handle tag color
        tag_color = request.form.get('tag_color', '#3B82F6').strip()
        if tag_color and re.match(r'^#[0-9A-Fa-f]{6}$', tag_color):
            datastore.data['settings']['application']['tags'][uuid]['tag_color'] = tag_color

        datastore.needs_write_urgent = True
        flash(gettext("Updated"))

        return redirect(url_for('tags.tags_overview_page'))


    @tags_blueprint.route("/delete/<string:uuid>", methods=['GET'])
    def form_tag_delete(uuid):
        return redirect(url_for('tags.tags_overview_page'))

    @tags_blueprint.route("/test-webhook/<string:uuid>", methods=['POST'])
    @login_optionally_required
    def test_slack_webhook(uuid):
        """
        Test a Slack webhook URL by sending a test message.

        Expects POST data with 'slack_webhook_url' field.
        Returns JSON response with success/failure status.
        """
        webhook_url = request.form.get('slack_webhook_url', '').strip()

        # Validate webhook URL is provided
        if not webhook_url:
            return jsonify({
                'success': False,
                'message': gettext('Please provide a Slack webhook URL')
            }), 400

        # Validate webhook URL format
        if not SLACK_WEBHOOK_PATTERN.match(webhook_url):
            return jsonify({
                'success': False,
                'message': gettext('Invalid Slack webhook URL format. Expected: https://hooks.slack.com/services/T<TEAM_ID>/B<BOT_ID>/<TOKEN>')
            }), 400

        # Get tag name for the test message
        tag_data = datastore.data['settings']['application']['tags'].get(uuid, {})
        tag_name = tag_data.get('title', 'Unknown Tag')

        # Prepare test message payload
        payload = {
            'text': f':white_check_mark: *Test Notification from changedetection.io*\n\nThis is a test message for tag: *{tag_name}*\n\nIf you see this message, your webhook is configured correctly!',
            'username': 'changedetection.io',
            'icon_emoji': ':robot_face:'
        }

        try:
            # Send test message to Slack
            response = requests.post(
                webhook_url,
                json=payload,
                timeout=10,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200 and response.text == 'ok':
                logger.info(f"Slack webhook test successful for tag {uuid}")
                return jsonify({
                    'success': True,
                    'message': gettext('Test message sent successfully! Check your Slack channel.')
                })
            else:
                logger.warning(f"Slack webhook test failed for tag {uuid}: {response.status_code} - {response.text}")
                return jsonify({
                    'success': False,
                    'message': gettext('Slack returned an error: %(error)s', error=response.text)
                }), 400

        except requests.exceptions.Timeout:
            logger.error(f"Slack webhook test timed out for tag {uuid}")
            return jsonify({
                'success': False,
                'message': gettext('Request timed out. Please check the webhook URL.')
            }), 500

        except requests.exceptions.ConnectionError:
            logger.error(f"Slack webhook test connection error for tag {uuid}")
            return jsonify({
                'success': False,
                'message': gettext('Could not connect to Slack. Please check your internet connection.')
            }), 500

        except Exception as e:
            logger.error(f"Slack webhook test error for tag {uuid}: {e}")
            return jsonify({
                'success': False,
                'message': gettext('An error occurred: %(error)s', error=str(e))
            }), 500

    return tags_blueprint
