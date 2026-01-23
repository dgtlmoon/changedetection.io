"""
Availability History API Endpoint (US-010)

Provides REST API access to availability history data for events/watches.
Enables dashboard to show 'sold out at' and 'restocked at' times.

Endpoints:
    GET /api/v1/watch/<uuid>/availability-history - Get availability history for an event
"""

import asyncio

from flask import request
from flask_restful import Resource, abort
from loguru import logger

from . import auth


class WatchAvailabilityHistory(Resource):
    """API endpoint for retrieving availability history of a watch/event."""

    def __init__(self, **kwargs):
        self.datastore = kwargs['datastore']

    @auth.check_token
    def get(self, uuid):
        """
        Get availability history for a watch/event.

        Query Parameters:
            limit (int): Maximum number of records to return (default: 100, max: 1000)

        Returns:
            JSON object with:
            - uuid: UUID of the event
            - count: Number of records returned
            - history: Array of availability history records, most recent first.
              Each record contains:
              - id: UUID of the availability history record
              - event_id: UUID of the event
              - is_sold_out: Boolean indicating sold out status at this point
              - recorded_at: ISO timestamp when recorded
            - sold_out_times: Array of times when event became sold out
            - restocked_times: Array of times when event became available again
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

        # Check if datastore has async availability history method (PostgreSQL store)
        if hasattr(self.datastore, 'get_availability_history'):
            try:
                # Run async method in sync context
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    history = loop.run_until_complete(
                        self.datastore.get_availability_history(
                            event_uuid=uuid,
                            limit=limit,
                        )
                    )
                finally:
                    loop.close()

                # Calculate sold out and restocked times from history
                sold_out_times = []
                restocked_times = []

                for record in history:
                    if record.get('is_sold_out'):
                        sold_out_times.append(record.get('recorded_at'))
                    else:
                        restocked_times.append(record.get('recorded_at'))

                return {
                    'uuid': uuid,
                    'count': len(history),
                    'history': history,
                    'sold_out_times': sold_out_times,
                    'restocked_times': restocked_times,
                }, 200

            except Exception as e:
                logger.error(f"Error fetching availability history for {uuid}: {e}")
                abort(500, message=f'Error fetching availability history: {str(e)}')

        # Fallback for non-PostgreSQL datastore - return empty
        return {
            'uuid': uuid,
            'count': 0,
            'history': [],
            'sold_out_times': [],
            'restocked_times': [],
            'message': 'Availability history not available for this datastore type',
        }, 200
