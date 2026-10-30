import time

from flask_restful import Resource
from . import auth, validate_openapi_request


def overdue_watch_uuids(datastore, now=None):
    """Watches that have not been checked but should have been: not checked within their interval, plus 5 minutes
    of grace. Paused watches (one by one, or all of them with "pause all") aren't supposed to be checked, so they're
    never overdue (#4607)."""
    now = time.time() if now is None else now
    if datastore.data['settings']['application'].get('all_paused'):
        return []

    overdue = []
    for uuid, watch in datastore.data.get('watching', {}).items():
        if watch.get('paused'):
            continue
        # see if now - last_checked is greater than the time that should have been
        # this is not super accurate (maybe they just edited it) but better than nothing
        threshold = watch.threshold_seconds() or datastore.threshold_seconds
        # Allow 5 minutes of grace time before we decide it's overdue
        if now - (watch.get('last_checked') or 0) - (5 * 60) > threshold:
            overdue.append(uuid)
    return overdue


class SystemInfo(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']
        self.new_version_available=kwargs['new_version_available']

    @auth.check_token
    @validate_openapi_request('getSystemInfo')
    def get(self):
        """Return system info."""
        overdue_watches = overdue_watch_uuids(self.datastore)
        from changedetectionio import __version__ as main_version, worker_pool
        from changedetectionio.api.operations import checking_now
        return {
            'checking_now': checking_now(self.datastore),
            'fetch_workers': worker_pool.get_worker_count(),
            'all_muted': self.datastore.data['settings']['application']['all_muted'],
            'all_paused': self.datastore.data['settings']['application']['all_paused'],
            'base_url': self.datastore.data['settings']['application']['base_url'],
            'new_version_available': self.new_version_available,
            'overdue_watches': overdue_watches,
            'queue_size': self.update_q.qsize(),
            'tag_count': len(self.datastore.data['settings']['application'].get('tags', {})),
            'uptime': round(time.time() - self.datastore.start_time, 2),
            'version': main_version,
            'watch_count': len(self.datastore.data.get('watching', {})),
        }, 200
