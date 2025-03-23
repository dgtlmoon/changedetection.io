from flask_restful import Resource
from . import auth


class SystemInfo(Resource):
    def __init__(self, **kwargs):
        # datastore is a black box dependency
        self.datastore = kwargs['datastore']
        self.update_q = kwargs['update_q']

    @auth.check_token
    def get(self):
        """
        @api {get} /api/v1/systeminfo Return system info
        @apiDescription Return some info about the current system state
        @apiExample {curl} Example usage:
            curl http://localhost:5000/api/v1/systeminfo -H"x-api-key:813031b16330fe25e3780cf0325daa45"
            HTTP/1.0 200
            {
                'queue_size': 10 ,
                'overdue_watches': ["watch-uuid-list"],
                'uptime': 38344.55,
                'watch_count': 800,
                'version': "0.40.1"
            }
        @apiName Get Info
        @apiGroup System Information
        """
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
                   'uptime': round(time.time() - self.datastore.start_time, 2),
                   'watch_count': len(self.datastore.data.get('watching', {})),
                   'version': main_version
               }, 200