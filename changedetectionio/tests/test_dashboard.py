#!/usr/bin/env python3
"""
Tests for the Dashboard - Metrics Display (US-018)
"""

from flask import url_for
from .util import live_server_setup


def test_dashboard_page_loads(client, live_server, measure_memory_usage, datastore_path):
    """Test that the dashboard page loads successfully."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Dashboard' in res.data


def test_dashboard_shows_total_events_metric(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows total events count."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Total Events' in res.data
    assert b'metric-total-events' in res.data


def test_dashboard_shows_sold_out_today_metric(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows sold out today count."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Sold Out Today' in res.data
    assert b'metric-sold-out-today' in res.data


def test_dashboard_shows_restocked_today_metric(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows restocked today count."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Restocked Today' in res.data
    assert b'metric-restocked-today' in res.data


def test_dashboard_shows_alerts_today_metric(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows alerts sent today count."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Alerts Sent Today' in res.data
    assert b'metric-alerts-today' in res.data


def test_dashboard_shows_recent_activity(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows recent activity feed."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Recent Activity' in res.data
    assert b'activity-feed' in res.data


def test_dashboard_shows_events_by_tag(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard shows events by tag breakdown."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'Events by Tag' in res.data
    assert b'tag-chart' in res.data


def test_dashboard_api_metrics_endpoint(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard API metrics endpoint returns JSON."""
    res = client.get(
        url_for("dashboard.api_metrics"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert res.content_type == 'application/json'

    data = res.get_json()
    assert data['success'] is True
    assert 'metrics' in data
    assert 'recent_activity' in data
    assert 'tag_breakdown' in data
    assert 'timestamp' in data


def test_dashboard_api_metrics_contains_all_metrics(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard API returns all required metrics."""
    res = client.get(
        url_for("dashboard.api_metrics"),
        follow_redirects=True
    )
    assert res.status_code == 200

    data = res.get_json()
    metrics = data['metrics']

    # Check all required metrics are present
    assert 'total_events' in metrics
    assert 'events_sold_out_today' in metrics
    assert 'events_restocked_today' in metrics
    assert 'alerts_sent_today' in metrics
    assert 'active_events' in metrics
    assert 'paused_events' in metrics
    assert 'errored_events' in metrics


def test_dashboard_has_auto_refresh(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard includes auto-refresh mechanism."""
    res = client.get(
        url_for("dashboard.dashboard_page"),
        follow_redirects=True
    )
    assert res.status_code == 200
    # Check for refresh indicator and JavaScript
    assert b'refresh-indicator' in res.data
    assert b'REFRESH_INTERVAL' in res.data
    assert b'refreshDashboard' in res.data


def test_dashboard_link_in_menu(client, live_server, measure_memory_usage, datastore_path):
    """Test that dashboard link appears in navigation menu."""
    res = client.get(
        url_for("watchlist.index"),
        follow_redirects=True
    )
    assert res.status_code == 200
    assert b'DASHBOARD' in res.data
    assert b'/dashboard/' in res.data
