"""
Dashboard Blueprint - Metrics Display

Provides a dashboard showing:
- Total events tracked count
- Events sold out today count
- Events restocked today count
- Alerts sent today count
- Recent activity feed (last 10 changes)
- Events by tag breakdown
- Auto-refresh via polling
"""

from collections import Counter
from datetime import datetime
from flask import Blueprint, jsonify, render_template
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    dashboard_blueprint = Blueprint('dashboard', __name__, template_folder="templates")

    @dashboard_blueprint.route("/", methods=['GET'])
    @login_optionally_required
    def dashboard_page():
        """Main dashboard page with metrics display."""
        metrics = _calculate_metrics(datastore)
        recent_activity = _get_recent_activity(datastore, limit=10)
        tag_breakdown = _get_tag_breakdown(datastore)

        return render_template(
            "dashboard.html",
            metrics=metrics,
            recent_activity=recent_activity,
            tag_breakdown=tag_breakdown,
        )

    @dashboard_blueprint.route("/api/metrics", methods=['GET'])
    @login_optionally_required
    def api_metrics():
        """API endpoint for dashboard metrics - used for auto-refresh."""
        try:
            metrics = _calculate_metrics(datastore)
            recent_activity = _get_recent_activity(datastore, limit=10)
            tag_breakdown = _get_tag_breakdown(datastore)

            return jsonify({
                'success': True,
                'metrics': metrics,
                'recent_activity': recent_activity,
                'tag_breakdown': tag_breakdown,
                'timestamp': datetime.now().isoformat(),
            })
        except Exception as e:
            logger.error(f"Dashboard metrics error: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
            }), 500

    return dashboard_blueprint


def _calculate_metrics(datastore: ChangeDetectionStore) -> dict:
    """
    Calculate dashboard metrics from the datastore.

    Returns dict with:
    - total_events: Total number of watches/events tracked
    - events_sold_out_today: Count of events that went sold out today
    - events_restocked_today: Count of events that were restocked today
    - alerts_sent_today: Count of notifications sent today
    - active_events: Count of non-paused events
    - paused_events: Count of paused events
    - errored_events: Count of events with errors
    """
    watches = datastore.data.get('watching', {})
    today = datetime.now().date()
    today_start = datetime.combine(today, datetime.min.time())
    today_start_ts = today_start.timestamp()

    total_events = len(watches)
    active_events = 0
    paused_events = 0
    errored_events = 0
    sold_out_today = 0
    restocked_today = 0
    alerts_sent_today = 0

    for uuid, watch in watches.items():
        # Count active vs paused
        if watch.get('paused', False):
            paused_events += 1
        else:
            active_events += 1

        # Count errored
        if watch.get('last_error'):
            errored_events += 1

        # Check price/restock data for today's changes
        restock_data = watch.get('restock', {})
        if restock_data:
            # Check if there was a sold_out change today
            last_changed = watch.get('last_changed', 0)
            if last_changed and last_changed >= today_start_ts:
                in_stock = restock_data.get('in_stock')
                # We track state changes based on current state
                # If in_stock is False, it means it's currently sold out
                if in_stock is False:
                    sold_out_today += 1
                elif in_stock is True:
                    # Check if this was a state change (restock)
                    # by looking at the history or tracking attribute
                    restocked_today += 1

        # Count notifications sent today from history
        # Notifications are tracked at the app level, not per watch
        # We'll estimate from the notification debug log

    # Get notification count from datastore settings if available
    from changedetectionio.flask_app import notification_debug_log
    for log_entry in notification_debug_log:
        try:
            # Log entries are in format "timestamp - SENDING - payload"
            if ' - SENDING - ' in log_entry:
                # Extract timestamp and check if it's today
                timestamp_str = log_entry.split(' - ')[0]
                # Handle various timestamp formats
                try:
                    log_time = datetime.strptime(timestamp_str, "%c")
                    if log_time.date() == today:
                        alerts_sent_today += 1
                except ValueError:
                    pass
        except Exception:
            pass

    return {
        'total_events': total_events,
        'active_events': active_events,
        'paused_events': paused_events,
        'errored_events': errored_events,
        'events_sold_out_today': sold_out_today,
        'events_restocked_today': restocked_today,
        'alerts_sent_today': alerts_sent_today,
    }


def _get_recent_activity(datastore: ChangeDetectionStore, limit: int = 10) -> list:
    """
    Get recent activity feed (last N changes).

    Returns list of dicts with:
    - uuid: Watch UUID
    - url: Watch URL
    - title: Watch title
    - last_changed: Timestamp of last change
    - change_type: Type of change (restock, sold_out, price_change, content)
    """
    watches = datastore.data.get('watching', {})
    activities = []

    for uuid, watch in watches.items():
        last_changed = watch.get('last_changed', 0)
        if last_changed and last_changed > 0:
            # Determine change type
            change_type = 'content'
            restock_data = watch.get('restock', {})
            if restock_data:
                in_stock = restock_data.get('in_stock')
                if in_stock is False:
                    change_type = 'sold_out'
                elif in_stock is True:
                    # Could be restock or price change
                    price = restock_data.get('price')
                    if price:
                        change_type = 'price_change'
                    else:
                        change_type = 'restock'

            activities.append({
                'uuid': uuid,
                'url': watch.get('url', ''),
                'title': watch.get('title') or watch.get('url', 'Unknown'),
                'last_changed': last_changed,
                'last_changed_human': _format_timestamp(last_changed),
                'change_type': change_type,
            })

    # Sort by last_changed descending and limit
    activities.sort(key=lambda x: x['last_changed'], reverse=True)
    return activities[:limit]


def _get_tag_breakdown(datastore: ChangeDetectionStore) -> list:
    """
    Get events by tag breakdown for chart display.

    Returns list of dicts with:
    - tag_id: Tag UUID
    - tag_name: Tag title
    - count: Number of watches with this tag
    - color: Tag color for chart
    """
    watches = datastore.data.get('watching', {})
    tags = datastore.data['settings']['application'].get('tags', {})

    # Count watches per tag
    tag_counts = Counter()
    untagged_count = 0

    for uuid, watch in watches.items():
        watch_tags = watch.get('tags', [])
        if watch_tags:
            for tag_id in watch_tags:
                tag_counts[tag_id] += 1
        else:
            untagged_count += 1

    # Build breakdown list
    breakdown = []
    for tag_id, count in tag_counts.items():
        tag_data = tags.get(tag_id, {})
        breakdown.append({
            'tag_id': tag_id,
            'tag_name': tag_data.get('title', 'Unknown'),
            'count': count,
            'color': tag_data.get('tag_color', '#3B82F6'),
        })

    # Add untagged category
    if untagged_count > 0:
        breakdown.append({
            'tag_id': 'untagged',
            'tag_name': 'Untagged',
            'count': untagged_count,
            'color': '#9CA3AF',  # Gray color for untagged
        })

    # Sort by count descending
    breakdown.sort(key=lambda x: x['count'], reverse=True)

    return breakdown


def _format_timestamp(timestamp: float) -> str:
    """Format a unix timestamp to a human-readable relative time."""
    import time
    try:
        import timeago
        return timeago.format(int(timestamp), time.time(), 'en')
    except Exception:
        # Fallback to basic formatting
        try:
            dt = datetime.fromtimestamp(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "Unknown"
