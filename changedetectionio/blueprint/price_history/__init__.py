"""
Price History Chart Blueprint (US-022)

Provides a price history visualization chart for events showing:
- Line chart with price_low and price_high as separate lines
- Sold out periods shown as shaded regions
- Hover tooltips with exact price and timestamp
- Time range selector (7 days, 30 days, 90 days, all)
"""

import asyncio
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request
from loguru import logger

from changedetectionio.store import ChangeDetectionStore
from changedetectionio.flask_app import login_optionally_required


def construct_blueprint(datastore: ChangeDetectionStore):
    price_history_blueprint = Blueprint(
        'price_history',
        __name__,
        template_folder="templates"
    )

    @price_history_blueprint.route("/<string:uuid>", methods=['GET'])
    @login_optionally_required
    def price_history_chart(uuid):
        """
        Display price history chart for a watch/event.

        Query Parameters:
            range: Time range filter ('7d', '30d', '90d', 'all')
        """
        # Verify watch exists
        watch = datastore.data['watching'].get(uuid)
        if not watch:
            return render_template(
                "price_history_chart.html",
                error="Watch not found",
                uuid=uuid,
                watch=None,
            ), 404

        # Get time range from query params
        time_range = request.args.get('range', '30d')
        valid_ranges = ['7d', '30d', '90d', 'all']
        if time_range not in valid_ranges:
            time_range = '30d'

        return render_template(
            "price_history_chart.html",
            uuid=uuid,
            watch=watch,
            time_range=time_range,
        )

    @price_history_blueprint.route("/<string:uuid>/data", methods=['GET'])
    @login_optionally_required
    def price_history_data(uuid):
        """
        API endpoint for fetching price history chart data.

        Query Parameters:
            range: Time range filter ('7d', '30d', '90d', 'all')

        Returns:
            JSON with price_history and availability_history data formatted
            for Chart.js consumption.
        """
        # Verify watch exists
        watch = datastore.data['watching'].get(uuid)
        if not watch:
            return jsonify({
                'success': False,
                'error': 'Watch not found',
            }), 404

        # Get time range from query params
        time_range = request.args.get('range', '30d')

        # Calculate date filter
        now = datetime.now()
        start_date = None
        if time_range == '7d':
            start_date = now - timedelta(days=7)
        elif time_range == '30d':
            start_date = now - timedelta(days=30)
        elif time_range == '90d':
            start_date = now - timedelta(days=90)
        # 'all' means no filter

        try:
            # Fetch price history
            price_history = []
            availability_history = []

            if hasattr(datastore, 'get_price_history'):
                # Use PostgreSQL store method
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    price_history_raw = loop.run_until_complete(
                        datastore.get_price_history(
                            event_uuid=uuid,
                            limit=1000,
                        )
                    )
                finally:
                    loop.close()

                # Filter by date if needed and format for chart
                for record in price_history_raw:
                    recorded_at = record.get('recorded_at')
                    if recorded_at:
                        # Parse ISO timestamp
                        try:
                            if isinstance(recorded_at, str):
                                dt = datetime.fromisoformat(
                                    recorded_at.replace('Z', '+00:00')
                                )
                            else:
                                dt = recorded_at

                            # Apply date filter
                            if start_date and dt.replace(tzinfo=None) < start_date:
                                continue

                            price_history.append({
                                'x': recorded_at,
                                'price_low': float(record.get('price_low') or 0),
                                'price_high': float(record.get('price_high') or 0),
                                'ticket_type': record.get('ticket_type'),
                            })
                        except (ValueError, TypeError) as e:
                            logger.debug(f"Error parsing price history date: {e}")

            if hasattr(datastore, 'get_availability_history'):
                # Use PostgreSQL store method
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    availability_history_raw = loop.run_until_complete(
                        datastore.get_availability_history(
                            event_uuid=uuid,
                            limit=1000,
                        )
                    )
                finally:
                    loop.close()

                # Filter by date if needed and format for chart
                for record in availability_history_raw:
                    recorded_at = record.get('recorded_at')
                    if recorded_at:
                        try:
                            if isinstance(recorded_at, str):
                                dt = datetime.fromisoformat(
                                    recorded_at.replace('Z', '+00:00')
                                )
                            else:
                                dt = recorded_at

                            # Apply date filter
                            if start_date and dt.replace(tzinfo=None) < start_date:
                                continue

                            availability_history.append({
                                'x': recorded_at,
                                'is_sold_out': record.get('is_sold_out', False),
                            })
                        except (ValueError, TypeError) as e:
                            logger.debug(
                                f"Error parsing availability history date: {e}"
                            )

            # Sort both arrays by date (oldest first for chart)
            price_history.sort(
                key=lambda x: x['x'] if x['x'] else '',
                reverse=False
            )
            availability_history.sort(
                key=lambda x: x['x'] if x['x'] else '',
                reverse=False
            )

            # Calculate sold-out regions for shading
            sold_out_regions = _calculate_sold_out_regions(availability_history)

            return jsonify({
                'success': True,
                'uuid': uuid,
                'time_range': time_range,
                'price_history': price_history,
                'availability_history': availability_history,
                'sold_out_regions': sold_out_regions,
                'watch_title': watch.get('title') or watch.get('url', 'Unknown'),
            })

        except Exception as e:
            logger.error(f"Error fetching price history data for {uuid}: {e}")
            return jsonify({
                'success': False,
                'error': str(e),
            }), 500

    return price_history_blueprint


def _calculate_sold_out_regions(availability_history: list) -> list:
    """
    Calculate sold-out time regions for chart shading.

    Returns list of dicts with 'start' and 'end' timestamps for periods
    where the event was sold out.
    """
    regions = []
    current_region_start = None

    for record in availability_history:
        is_sold_out = record.get('is_sold_out', False)
        timestamp = record.get('x')

        if is_sold_out and current_region_start is None:
            # Start of a sold-out period
            current_region_start = timestamp
        elif not is_sold_out and current_region_start is not None:
            # End of a sold-out period
            regions.append({
                'start': current_region_start,
                'end': timestamp,
            })
            current_region_start = None

    # If still in a sold-out period at the end, extend to now
    if current_region_start is not None:
        regions.append({
            'start': current_region_start,
            'end': datetime.now().isoformat(),
        })

    return regions
