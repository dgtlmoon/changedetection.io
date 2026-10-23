from flask_restful import Resource
from . import auth, validate_openapi_request


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
        import time
        overdue_watches = []

        # Check all watches and report which have not been checked but should have been

        for uuid, watch in self.datastore.data.get('watching', {}).items():
            # see if now - last_checked is greater than the time that should have been
            # this is not super accurate (maybe they just edited it) but better than nothing
            t = watch.threshold_seconds()
            if not t:
                # Use the system wide default
                t = self.datastore.threshold_seconds

            time_since_check = time.time() - watch.get('last_checked')

            # Allow 5 minutes of grace time before we decide it's overdue
            if time_since_check - (5 * 60) > t:
                overdue_watches.append(uuid)
        from changedetectionio import __version__ as main_version
        return {
                   'queue_size': self.update_q.qsize(),
                   'overdue_watches': overdue_watches,
                   'watch_count': len(self.datastore.data.get('watching', {})),
                   'tag_count': len(self.datastore.data['settings']['application'].get('tags', {})),
                   'all_paused': self.datastore.data['settings']['application']['all_paused'],
                   'all_muted': self.datastore.data['settings']['application']['all_muted'],
                   'base_url': self.datastore.data['settings']['application']['base_url'],
                   'uptime': round(time.time() - self.datastore.start_time, 2),
                   'version': main_version,
                   'new_version_available': self.new_version_available
               }, 200