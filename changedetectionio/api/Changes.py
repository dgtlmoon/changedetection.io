import os

from flask import make_response, request
from flask_restful import Resource, abort

from . import auth, validate_openapi_request

# Seconds a single /api/v1/changes request may spend reading snapshots before it returns what it has
CHANGES_TIME_BUDGET = float(os.getenv('CHANGES_TIME_BUDGET_SECONDS', 20))


class Changes(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']

    def _int_arg(self, name, default, minimum, maximum):
        value = request.args.get(name)
        if value is None or value == '':
            return default
        try:
            value = int(value)
        except ValueError:
            abort(400, message=f"'{name}' must be a whole number")
        if not minimum <= value <= maximum:
            abort(400, message=f"'{name}' must be between {minimum} and {maximum}")
        return value

    @auth.check_token
    @validate_openapi_request('getChanges')
    def get(self):
        """Every change across a group of watches between two dates, as unified diffs."""
        import time
        from changedetectionio.changes_report import MODES, group_changes, parse_timestamp, render_unified, select_watches

        from_ts = parse_timestamp(request.args.get('from'))
        if from_ts is None:
            abort(400, message="'from' is required, as unix seconds or an ISO date like 2026-10-01")
        to_ts = parse_timestamp(request.args.get('to')) if request.args.get('to') else int(time.time())
        if to_ts is None:
            abort(400, message="'to' must be unix seconds or an ISO date like 2026-10-31")
        if to_ts <= from_ts:
            abort(400, message="'to' must be after 'from'")

        mode = request.args.get('mode', 'net_change')
        if mode not in MODES:
            abort(400, message=f"'mode' must be one of: {', '.join(MODES)}")
        output_format = request.args.get('format', 'unified')
        if output_format not in ('unified', 'json'):
            abort(400, message="'format' must be 'unified' or 'json'")

        context = self._int_arg('context', 1, 0, 10)
        max_lines = self._int_arg('max_lines_per_watch', 200, 0, 5000)
        limit = self._int_arg('limit', 50, 1, 1000)
        offset = self._int_arg('offset', 0, 0, 10_000_000)

        uuids = request.args.get('uuids', '').split(',')
        try:
            watches = select_watches(self.datastore, tag=request.args.get('tag'), uuids=uuids)
        except LookupError as e:
            abort(404, message=str(e))

        # Bounded, it runs inside a request in the single app process (see group_changes)
        report = group_changes(watches, from_ts, to_ts, mode=mode, context=context, max_lines=max_lines,
                               limit=limit, offset=offset, time_budget=CHANGES_TIME_BUDGET)
        if output_format == 'json':
            return report, 200

        response = make_response(render_unified(report), 200)
        response.mimetype = 'text/plain'
        return response
