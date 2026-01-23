"""
Alert History Blueprint (US-023)

Provides an alert history view showing sent notifications:
- Filter by alert type (restock, price change, sold out)
- Filter by event or tag
- Shows: timestamp, event name, alert type, target webhook, success/failure
- Click to view full notification payload
- Pagination for large history
"""

import asyncio
import json

from flask import Blueprint, jsonify, render_template, request
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    alert_history_blueprint = Blueprint(
        'alert_history',
        __name__,
        template_folder="templates"
    )

    @alert_history_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def alert_history_page():
        """
        Display alert history page.

        Query Parameters:
            type: Filter by notification type (restock, price_change, sold_out, new_event, error)
            event: Filter by event UUID
            tag: Filter by tag UUID
            status: Filter by success status (success, failed, all)
            page: Page number (default: 1)
            per_page: Items per page (default: 50)
        """
        # Get filter parameters
        notification_type = request.args.get('type', '')
        event_uuid = request.args.get('event', '')
        tag_uuid = request.args.get('tag', '')
        status_filter = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)

        # Validate per_page
        if per_page not in [25, 50, 100]:
            per_page = 50

        # Validate page
        if page < 1:
            page = 1

        # Get available events and tags for filter dropdowns
        events = []
        tags = []

        try:
            watches = datastore.data.get('watching', {})
            for uuid, watch in watches.items():
                events.append({
                    'uuid': uuid,
                    'title': watch.get('title') or watch.get('url', 'Unknown'),
                })

            # Sort events by title
            events.sort(key=lambda x: x['title'].lower())

            # Get tags from settings
            app_tags = datastore.data.get('settings', {}).get('application', {}).get('tags', {})
            for tag_id, tag_data in app_tags.items():
                tags.append({
                    'uuid': tag_id,
                    'title': tag_data.get('title', 'Unknown'),
                })

            # Sort tags by title
            tags.sort(key=lambda x: x['title'].lower())

        except Exception as e:
            logger.error(f"Error loading events/tags for alert history: {e}")

        # Get notification logs from datastore
        logs = []
        total_count = 0
        total_pages = 1

        if hasattr(datastore, 'get_notification_logs'):
            try:
                # Convert status filter to boolean
                success_filter = None
                if status_filter == 'success':
                    success_filter = True
                elif status_filter == 'failed':
                    success_filter = False

                # Calculate offset
                offset = (page - 1) * per_page

                # Fetch logs
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    logs, total_count = loop.run_until_complete(
                        datastore.get_notification_logs(
                            limit=per_page,
                            offset=offset,
                            notification_type=notification_type if notification_type else None,
                            event_uuid=event_uuid if event_uuid else None,
                            tag_uuid=tag_uuid if tag_uuid else None,
                            success=success_filter,
                        )
                    )
                finally:
                    loop.close()

                # Calculate total pages
                total_pages = max(1, (total_count + per_page - 1) // per_page)

            except Exception as e:
                logger.error(f"Error fetching notification logs: {e}")

        # Define notification types for filter dropdown
        notification_types = [
            {'value': 'restock', 'label': 'Restock'},
            {'value': 'price_change', 'label': 'Price Change'},
            {'value': 'sold_out', 'label': 'Sold Out'},
            {'value': 'new_event', 'label': 'New Event'},
            {'value': 'error', 'label': 'Error'},
        ]

        return render_template(
            "alert_history.html",
            logs=logs,
            events=events,
            tags=tags,
            notification_types=notification_types,
            current_type=notification_type,
            current_event=event_uuid,
            current_tag=tag_uuid,
            current_status=status_filter,
            page=page,
            per_page=per_page,
            total_count=total_count,
            total_pages=total_pages,
        )

    @alert_history_blueprint.route("/data", methods=['GET'])
    @login_optionally_required
    def alert_history_data():
        """
        API endpoint for fetching alert history data.

        Query Parameters:
            type: Filter by notification type
            event: Filter by event UUID
            tag: Filter by tag UUID
            status: Filter by success status (success, failed, all)
            page: Page number (default: 1)
            per_page: Items per page (default: 50)

        Returns:
            JSON with logs array, pagination info, and stats
        """
        # Get filter parameters
        notification_type = request.args.get('type', '')
        event_uuid = request.args.get('event', '')
        tag_uuid = request.args.get('tag', '')
        status_filter = request.args.get('status', 'all')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 50, type=int)

        # Validate parameters
        if per_page not in [25, 50, 100]:
            per_page = 50
        if page < 1:
            page = 1

        if not hasattr(datastore, 'get_notification_logs'):
            return jsonify({
                'success': False,
                'error': 'Notification logs not available',
            }), 501

        try:
            # Convert status filter to boolean
            success_filter = None
            if status_filter == 'success':
                success_filter = True
            elif status_filter == 'failed':
                success_filter = False

            # Calculate offset
            offset = (page - 1) * per_page

            # Fetch logs
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                logs, total_count = loop.run_until_complete(
                    datastore.get_notification_logs(
                        limit=per_page,
                        offset=offset,
                        notification_type=notification_type if notification_type else None,
                        event_uuid=event_uuid if event_uuid else None,
                        tag_uuid=tag_uuid if tag_uuid else None,
                        success=success_filter,
                    )
                )
            finally:
                loop.close()

            # Calculate total pages
            total_pages = max(1, (total_count + per_page - 1) // per_page)

            return jsonify({
                'success': True,
                'logs': logs,
                'page': page,
                'per_page': per_page,
                'total_count': total_count,
                'total_pages': total_pages,
            })

        except Exception as e:
            logger.error(f"Error fetching notification logs: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
            }), 500

    @alert_history_blueprint.route("/<string:log_id>", methods=['GET'])
    @login_optionally_required
    def alert_history_detail(log_id):
        """
        API endpoint for fetching a single notification log detail.

        Args:
            log_id: UUID of the notification log

        Returns:
            JSON with full notification log details including payload
        """
        if not hasattr(datastore, 'get_notification_log_by_id'):
            return jsonify({
                'success': False,
                'error': 'Notification logs not available',
            }), 501

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                log = loop.run_until_complete(
                    datastore.get_notification_log_by_id(log_id)
                )
            finally:
                loop.close()

            if not log:
                return jsonify({
                    'success': False,
                    'error': 'Notification log not found',
                }), 404

            return jsonify({
                'success': True,
                'log': log,
            })

        except Exception as e:
            logger.error(f"Error fetching notification log {log_id}: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
            }), 500

    @alert_history_blueprint.route("/stats", methods=['GET'])
    @login_optionally_required
    def alert_history_stats():
        """
        API endpoint for fetching notification log statistics.

        Returns:
            JSON with total_count, success_count, failure_count, and counts by type
        """
        if not hasattr(datastore, 'get_notification_log_stats'):
            return jsonify({
                'success': False,
                'error': 'Notification logs not available',
            }), 501

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                stats = loop.run_until_complete(
                    datastore.get_notification_log_stats()
                )
            finally:
                loop.close()

            return jsonify({
                'success': True,
                'stats': stats,
            })

        except Exception as e:
            logger.error(f"Error fetching notification log stats: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
            }), 500

    return alert_history_blueprint
