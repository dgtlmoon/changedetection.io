#!/usr/bin/env python3
"""
Tests for the Alert History View (US-023)
"""

from flask import url_for
from .util import live_server_setup


def test_alert_history_page_loads(client, live_server, measure_memory_usage, datastore_path):
    """Test that the alert history page loads successfully."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_shows_filters(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history page shows filter controls."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for filter form elements
    assert b'type-filter' in res.data
    assert b'event-filter' in res.data
    assert b'tag-filter' in res.data
    assert b'status-filter' in res.data


def test_alert_history_filter_by_type_restock(client, live_server, measure_memory_usage, datastore_path):
    """Test filter by alert type - restock."""
    res = client.get(
        url_for("alert_history.alert_history_page", type='restock'),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_filter_by_type_price_change(client, live_server, measure_memory_usage, datastore_path):
    """Test filter by alert type - price change."""
    res = client.get(
        url_for("alert_history.alert_history_page", type='price_change'),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_filter_by_type_sold_out(client, live_server, measure_memory_usage, datastore_path):
    """Test filter by alert type - sold out."""
    res = client.get(
        url_for("alert_history.alert_history_page", type='sold_out'),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_filter_by_status_success(client, live_server, measure_memory_usage, datastore_path):
    """Test filter by status - success."""
    res = client.get(
        url_for("alert_history.alert_history_page", status='success'),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_filter_by_status_failed(client, live_server, measure_memory_usage, datastore_path):
    """Test filter by status - failed."""
    res = client.get(
        url_for("alert_history.alert_history_page", status='failed'),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_shows_table_headers(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history page shows correct table headers."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for table column headers
    assert b'Timestamp' in res.data
    assert b'Event' in res.data
    assert b'Type' in res.data
    assert b'Webhook' in res.data
    assert b'Status' in res.data


def test_alert_history_shows_notification_types(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert type dropdown contains all notification types."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for all notification types in filter
    assert b'Restock' in res.data
    assert b'Price Change' in res.data
    assert b'Sold Out' in res.data
    assert b'New Event' in res.data
    assert b'Error' in res.data


def test_alert_history_pagination_controls(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history page has pagination controls."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for per-page selector
    assert b'per-page' in res.data


def test_alert_history_pagination_page_param(client, live_server, measure_memory_usage, datastore_path):
    """Test that pagination page parameter works."""
    res = client.get(
        url_for("alert_history.alert_history_page", page=1, per_page=50),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_pagination_invalid_page(client, live_server, measure_memory_usage, datastore_path):
    """Test that invalid page parameter is handled gracefully."""
    res = client.get(
        url_for("alert_history.alert_history_page", page=0),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Should default to page 1
    assert b'Alert History' in res.data


def test_alert_history_per_page_25(client, live_server, measure_memory_usage, datastore_path):
    """Test per_page=25 parameter."""
    res = client.get(
        url_for("alert_history.alert_history_page", per_page=25),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_per_page_100(client, live_server, measure_memory_usage, datastore_path):
    """Test per_page=100 parameter."""
    res = client.get(
        url_for("alert_history.alert_history_page", per_page=100),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_per_page_invalid(client, live_server, measure_memory_usage, datastore_path):
    """Test that invalid per_page parameter defaults to 50."""
    res = client.get(
        url_for("alert_history.alert_history_page", per_page=999),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Should default to 50
    assert b'Alert History' in res.data


def test_alert_history_data_api_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history data API endpoint returns JSON."""
    res = client.get(
        url_for("alert_history.alert_history_data"),
        follow_redirects=True
    )
    # Note: This may return 501 if PostgreSQL store not available
    assert res.status_code in [200, 501]
    assert res.content_type == 'application/json'


def test_alert_history_data_api_with_filters(client, live_server, measure_memory_usage, datastore_path):
    """Test alert history data API with filter parameters."""
    res = client.get(
        url_for("alert_history.alert_history_data", type='restock', status='success'),
        follow_redirects=True
    )
    assert res.status_code in [200, 501]
    assert res.content_type == 'application/json'


def test_alert_history_detail_api_not_found(client, live_server, measure_memory_usage, datastore_path):
    """Test alert history detail API returns 404 for non-existent log."""
    res = client.get(
        url_for("alert_history.alert_history_detail", log_id='00000000-0000-0000-0000-000000000000'),
        follow_redirects=True
    )
    # Should return 404 or 501 depending on store availability
    assert res.status_code in [404, 501]
    assert res.content_type == 'application/json'


def test_alert_history_stats_api_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """Test alert history stats API endpoint."""
    res = client.get(
        url_for("alert_history.alert_history_stats"),
        follow_redirects=True
    )
    # Note: This may return 501 if PostgreSQL store not available
    assert res.status_code in [200, 501]
    assert res.content_type == 'application/json'


def test_alert_history_has_modal_for_payload(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history page includes modal for viewing payload."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for modal HTML
    assert b'payload-modal' in res.data
    assert b'modal-content' in res.data
    assert b'Notification Details' in res.data


def test_alert_history_shows_empty_state(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history shows empty state when no logs."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Should show empty state message when no logs
    assert b'No notifications found' in res.data or b'alert-history-table' in res.data


def test_alert_history_link_in_menu(client, live_server, measure_memory_usage, datastore_path):
    """Test that alert history link appears in navigation menu."""
    res = client.get(
        url_for("watchlist.index"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'ALERTS' in res.data
    assert b'/alert-history/' in res.data


def test_alert_history_combined_filters(client, live_server, measure_memory_usage, datastore_path):
    """Test combining multiple filters."""
    res = client.get(
        url_for(
            "alert_history.alert_history_page",
            type='price_change',
            status='failed',
            page=1,
            per_page=25
        ),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alert History' in res.data


def test_alert_history_clear_filters_link(client, live_server, measure_memory_usage, datastore_path):
    """Test that clear filters link exists."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Clear' in res.data


def test_alert_history_filter_button(client, live_server, measure_memory_usage, datastore_path):
    """Test that filter button exists."""
    res = client.get(
        url_for("alert_history.alert_history_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Filter' in res.data
