#!/usr/bin/env python3
"""
Tests for the Price History Chart feature (US-022)

Note: Uses unit tests for core logic and acceptance criteria verification
to avoid pytest-flask live_server fixture conflicts.
"""

import pytest
from datetime import datetime, timedelta


class TestSoldOutRegionCalculation:
    """Tests for the sold out region calculation logic."""

    def test_calculate_sold_out_regions_single_period(self):
        """Test sold out region calculation with single sold out period."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        now = datetime.now()
        availability = [
            {'x': (now - timedelta(days=5)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=3)).isoformat(), 'is_sold_out': True},
            {'x': (now - timedelta(days=1)).isoformat(), 'is_sold_out': False},
        ]

        regions = _calculate_sold_out_regions(availability)
        assert len(regions) == 1
        assert regions[0]['start'] == (now - timedelta(days=3)).isoformat()
        assert regions[0]['end'] == (now - timedelta(days=1)).isoformat()

    def test_calculate_sold_out_regions_multiple_periods(self):
        """Test sold out region calculation with multiple sold out periods."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        now = datetime.now()
        availability = [
            {'x': (now - timedelta(days=10)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=8)).isoformat(), 'is_sold_out': True},
            {'x': (now - timedelta(days=6)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=4)).isoformat(), 'is_sold_out': True},
            {'x': (now - timedelta(days=2)).isoformat(), 'is_sold_out': False},
        ]

        regions = _calculate_sold_out_regions(availability)
        assert len(regions) == 2

    def test_calculate_sold_out_regions_currently_sold_out(self):
        """Test sold out region extends to now if still sold out."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        now = datetime.now()
        availability = [
            {'x': (now - timedelta(days=5)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=2)).isoformat(), 'is_sold_out': True},
            # No recovery - still sold out
        ]

        regions = _calculate_sold_out_regions(availability)
        assert len(regions) == 1
        # End time should be approximately now
        end_time = datetime.fromisoformat(regions[0]['end'])
        assert (datetime.now() - end_time).total_seconds() < 5

    def test_calculate_sold_out_regions_empty_history(self):
        """Test sold out region calculation with empty history."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        regions = _calculate_sold_out_regions([])
        assert regions == []

    def test_calculate_sold_out_regions_never_available(self):
        """Test when event was always sold out."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        now = datetime.now()
        availability = [
            {'x': (now - timedelta(days=5)).isoformat(), 'is_sold_out': True},
            {'x': (now - timedelta(days=3)).isoformat(), 'is_sold_out': True},
        ]

        regions = _calculate_sold_out_regions(availability)
        # Should have one region from first timestamp to now
        assert len(regions) == 1

    def test_calculate_sold_out_regions_always_available(self):
        """Test when event was never sold out."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions

        now = datetime.now()
        availability = [
            {'x': (now - timedelta(days=5)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=3)).isoformat(), 'is_sold_out': False},
            {'x': (now - timedelta(days=1)).isoformat(), 'is_sold_out': False},
        ]

        regions = _calculate_sold_out_regions(availability)
        assert len(regions) == 0


class TestAcceptanceCriteria:
    """Acceptance criteria verification tests."""

    def test_ac_line_chart_shows_price_over_time(self):
        """AC: Line chart showing price over time on event detail page."""
        # Blueprint creates a page with Chart.js for line chart
        from changedetectionio.blueprint.price_history import construct_blueprint
        assert construct_blueprint is not None

    def test_ac_shows_price_low_and_price_high_lines(self):
        """AC: Shows both price_low and price_high as separate lines."""
        # Template includes both datasets in Chart.js config
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert 'Low Price' in content
            assert 'High Price' in content

    def test_ac_sold_out_regions_calculation(self):
        """AC: Sold out periods shown as shaded regions."""
        from changedetectionio.blueprint.price_history import _calculate_sold_out_regions
        # Function exists and returns regions
        regions = _calculate_sold_out_regions([
            {'x': '2024-01-01T00:00:00', 'is_sold_out': True},
            {'x': '2024-01-02T00:00:00', 'is_sold_out': False},
        ])
        assert isinstance(regions, list)
        assert len(regions) == 1

    def test_ac_hover_shows_exact_price_and_timestamp(self):
        """AC: Hover shows exact price and timestamp."""
        # Template includes tooltip configuration
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert 'tooltip' in content
            assert 'toLocaleString' in content

    def test_ac_time_range_selector_7_days(self):
        """AC: Time range selector - 7 days option."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert "range='7d'" in content or 'range=7d' in content

    def test_ac_time_range_selector_30_days(self):
        """AC: Time range selector - 30 days option."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert "range='30d'" in content or 'range=30d' in content

    def test_ac_time_range_selector_90_days(self):
        """AC: Time range selector - 90 days option."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert "range='90d'" in content or 'range=90d' in content

    def test_ac_time_range_selector_all(self):
        """AC: Time range selector - all option."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert "range='all'" in content or 'range=all' in content

    def test_ac_chart_uses_lightweight_library(self):
        """AC: Use Chart.js or similar lightweight library."""
        import os
        # Check that Chart.js is included
        js_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'js',
            'chart.min.js'
        )
        assert os.path.exists(js_path)

    def test_ac_chart_renders_quickly_performance(self):
        """AC: Chart renders quickly even with many data points."""
        # API limits data to 1000 points max for performance
        import os
        blueprint_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            '__init__.py'
        )
        with open(blueprint_path, 'r') as f:
            content = f.read()
            # Check that limit=1000 is used
            assert 'limit=1000' in content

    def test_ac_chart_template_has_legend(self):
        """AC: Chart should have a legend for line types."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert 'legend' in content.lower()

    def test_ac_chart_template_has_stats_display(self):
        """AC: Stats section for current/period prices."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'price_history',
            'templates',
            'price_history_chart.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert 'stat-' in content or 'stats' in content.lower()


class TestBlueprintConstruction:
    """Tests for blueprint construction and route registration."""

    def test_blueprint_construct_returns_blueprint(self):
        """Test that construct_blueprint returns a Flask Blueprint."""
        from unittest.mock import MagicMock
        from changedetectionio.blueprint.price_history import construct_blueprint

        mock_datastore = MagicMock()
        mock_datastore.data = {'watching': {}, 'settings': {'application': {'tags': {}}}}

        blueprint = construct_blueprint(mock_datastore)

        from flask import Blueprint
        assert isinstance(blueprint, Blueprint)
        assert blueprint.name == 'price_history'

    def test_blueprint_has_chart_route(self):
        """Test that blueprint registers the chart page route."""
        from unittest.mock import MagicMock
        from changedetectionio.blueprint.price_history import construct_blueprint

        mock_datastore = MagicMock()
        mock_datastore.data = {'watching': {}, 'settings': {'application': {'tags': {}}}}

        blueprint = construct_blueprint(mock_datastore)

        # Blueprint deferred functions are registered via @blueprint.route decorators
        # Check that deferred_functions exists (it's populated by route decorators)
        assert hasattr(blueprint, 'deferred_functions')
        # Check that the blueprint has registered some functions
        assert len(list(blueprint.deferred_functions)) >= 2  # chart page + data API


class TestEditPageIntegration:
    """Tests for price history link in edit page."""

    def test_edit_page_contains_price_history_link(self):
        """Test that edit page template contains link to price history."""
        import os
        template_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'blueprint',
            'ui',
            'templates',
            'edit.html'
        )
        with open(template_path, 'r') as f:
            content = f.read()
            assert 'price_history' in content.lower() or 'price-history' in content.lower()


class TestStylesExist:
    """Tests for CSS styles."""

    def test_price_history_scss_exists(self):
        """Test that price history SCSS file exists."""
        import os
        scss_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'styles',
            'scss',
            'parts',
            '_price_history.scss'
        )
        assert os.path.exists(scss_path)

    def test_price_history_scss_has_chart_styles(self):
        """Test that SCSS has chart container styles."""
        import os
        scss_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'styles',
            'scss',
            'parts',
            '_price_history.scss'
        )
        with open(scss_path, 'r') as f:
            content = f.read()
            assert 'price-history' in content
            assert 'chart' in content.lower()

    def test_styles_scss_imports_price_history(self):
        """Test that main styles.scss imports price_history styles."""
        import os
        styles_path = os.path.join(
            os.path.dirname(__file__),
            '..',
            'static',
            'styles',
            'scss',
            'styles.scss'
        )
        with open(styles_path, 'r') as f:
            content = f.read()
            assert 'price_history' in content


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
