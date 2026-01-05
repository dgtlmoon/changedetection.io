#!/usr/bin/env python3

"""
Notification Dashboard Blueprint
Handles the notification queue dashboard UI and related functionality
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint():
    """Construct and return the notification dashboard blueprint"""
    notification_dashboard = Blueprint('notification_dashboard', __name__, template_folder='templates')

    @notification_dashboard.route("/", methods=['GET'])
    @login_optionally_required
    def dashboard():
        """Notification queue dashboard - shows pending, retrying, and failed notifications"""
        from changedetectionio.notification.task_queue import (
            get_pending_notifications,
            get_failed_notifications,
            get_retry_config,
            get_last_successful_notification
        )

        # Get pending/retrying notifications
        pending_list = get_pending_notifications(limit=1000)
        pending_count = len(pending_list) if pending_list else 0

        # Get failed (dead letter) notifications
        failed_notifications = get_failed_notifications()

        # Get retry configuration for display
        retry_config = get_retry_config()

        # Get last successful notification for reference
        last_success = get_last_successful_notification()

        return render_template(
            'notification-dashboard.html',
            pending_list=pending_list,
            pending_count=pending_count,
            failed_notifications=failed_notifications,
            retry_config=retry_config,
            last_success=last_success
        )

    @notification_dashboard.route("/log/<task_id>", methods=['GET'])
    @login_optionally_required
    def get_notification_log(task_id):
        """Get Apprise log for a specific notification task"""
        from changedetectionio.notification.task_queue import get_task_apprise_log

        log_data = get_task_apprise_log(task_id)

        if log_data:
            return jsonify(log_data)
        else:
            return jsonify({'error': 'Log not found for this task'}), 404

    @notification_dashboard.route("/send-now/<task_id>", methods=['GET'])
    @login_optionally_required
    def send_now(task_id):
        """Execute a scheduled notification immediately"""
        from changedetectionio.notification.task_queue import execute_scheduled_notification

        success = execute_scheduled_notification(task_id)
        if success:
            message = "✓ Notification sent successfully and removed from queue."
            flash(message, 'notice')
        else:
            message = "Failed to send notification. It remains scheduled for automatic retry."
            flash(message, 'error')

        return redirect(url_for('notification_dashboard.dashboard'))

    @notification_dashboard.route("/retry/<task_id>", methods=['POST'])
    @login_optionally_required
    def retry_notification(task_id):
        """Retry a failed notification (from dead letter queue)"""
        from changedetectionio.notification.task_queue import retry_failed_notification

        success = retry_failed_notification(task_id)
        message = f"Notification queued for retry." if success else f"Failed to retry notification. Check logs for details."

        if success:
            flash(message, 'notice')
        else:
            flash(message, 'error')

        return redirect(url_for('notification_dashboard.dashboard'))

    @notification_dashboard.route("/retry-all", methods=['POST'])
    @login_optionally_required
    def retry_all_notifications():
        """Retry all failed notifications"""
        from changedetectionio.notification.task_queue import retry_all_failed_notifications

        result = retry_all_failed_notifications()

        if result['total'] == 0:
            flash("No failed notifications to retry.", 'notice')
        elif result['failed'] == 0:
            flash(f"Successfully queued {result['success']} notification(s) for retry.", 'notice')
        else:
            flash(f"Queued {result['success']} notification(s) for retry. {result['failed']} failed to queue.", 'error')

        return redirect(url_for('notification_dashboard.dashboard'))

    @notification_dashboard.route("/clear-all", methods=['POST'])
    @login_optionally_required
    def clear_all_notifications():
        """Clear ALL notifications (pending, retrying, and failed)"""
        from changedetectionio.notification.task_queue import clear_all_notifications

        result = clear_all_notifications()

        if 'error' in result:
            flash(f"Error clearing notifications: {result['error']}", 'error')
        else:
            total_cleared = result.get('queue', 0) + result.get('schedule', 0) + result.get('results', 0)
            flash(f"Cleared {total_cleared} notification(s) from queue.", 'notice')

        return redirect(url_for('notification_dashboard.dashboard'))

    return notification_dashboard
