"""
Price History API Endpoint (US-009)

Provides REST API access to price history data for events/watches.

Endpoints:
    GET /api/v1/watch/<uuid>/price-history - Get price history for an event
"""

import asyncio

from flask import request
from flask_restful import Resource, abort
from loguru import logger

from . import auth


class WatchPriceHistory(Resource):
    """API endpoint for retrieving price history of a watch/event."""

    def __init__(self, **kwargs):
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self, uuid):
        """
        Get price history for a watch/event.

        Query Parameters:
            limit (int): Maximum number of records to return (default: 100, max: 1000)
            ticket_type (str): Filter by ticket type (optional)

        Returns:
            JSON array of price history records, most recent first.
            Each record contains:
            - id: UUID of the price history record
            - event_id: UUID of the event
            - price_low: Low price at this point
            - price_high: High price at this point
            - ticket_type: Ticket type (if tracked)
            - recorded_at: ISO timestamp when recorded
        """
        # Verify watch exists
        watch = self.datastore.data['watching'].get(uuid)
        if not watch:
            abort(404, message=f'No watch exists with the UUID of {uuid}')

        # Parse query parameters
        try:
            limit = min(int(request.args.get('limit', 100)), 1000)
        except (ValueError, TypeError):
            limit = 100

        ticket_type = request.args.get('ticket_type')

        # Check if datastore has async price history method (PostgreSQL store)
        if hasattr(self.datastore, 'get_price_history'):
            try:
                # Run async method in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    history = loop.run_until_complete(
                        self.datastore.get_price_history(
                            event_uuid=uuid,
                            limit=limit,
                            ticket_type=ticket_type,
                        )
                    )
                finally:
                    loop.close()

                return {
                    'uuid': uuid,
                    'count': len(history),
                    'history': history,
                }, 200

            except Exception as e:
                logger.error(f"Error fetching price history for {uuid}: {e}")
                abort(500, message=f'Error fetching price history: {str(e)}')

        # Fallback for non-PostgreSQL datastore - return empty
        return {
            'uuid': uuid,
            'count': 0,
            'history': [],
            'message': 'Price history not available for this datastore type',
        }, 200
