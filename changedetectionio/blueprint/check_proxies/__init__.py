from concurrent.futures import ThreadPoolExecutor
from distutils.util import strtobool
from functools import wraps

from flask import Blueprint, flash, redirect, url_for
from flask_login import login_required

from changedetectionio.processors import text_json_diff
from changedetectionio.store import ChangeDetectionStore
from changedetectionio import queuedWatchMetaData
from queue import PriorityQueue

STATUS_CHECKING = 0
STATUS_FAILED = 1
STATUS_OK = 2
_DEFAULT_POOL = ThreadPoolExecutor()


# Maybe use fetch-time if its >5 to show some expected load time?
def threadpool(f, executor=None):
    @wraps(f)
    def wrap(*args, **kwargs):
        return (executor or _DEFAULT_POOL).submit(f, *args, **kwargs)

    return wrap


def construct_blueprint(datastore: ChangeDetectionStore):
    check_proxies_blueprint = Blueprint('check_proxies', __name__)
    checks_in_progress = {}

    @threadpool
    def long_task(x, uuid, preferred_proxy):
        from changedetectionio import content_fetcher
        status = {}
        contents = ''
        try:
            update_handler = text_json_diff.perform_site_check(datastore=datastore)
            changed_detected, update_obj, contents = update_handler.run(uuid, preferred_proxy=preferred_proxy)

        except content_fetcher.Non200ErrorCodeReceived as e:
            status = {'status': 'ERROR', 'length': len(contents), 'status_code': e.status_code}
        except Exception as e:
            status = {'status': 'ERROR OTHER', 'length': len(contents) if contents else 0}
        else:
            status = {'status': 'OK', 'length': len(contents), 'status_code': 200}

        return status

    @login_required
    @check_proxies_blueprint.route("/<string:uuid>/status", methods=['GET'])
    def get_recheck_status(uuid):

        results = {}
        for k, v in checks_in_progress.get(uuid, {}).items():
            try:
                r_1 = v.result(timeout=0.05)
            except Exception as e:
                # If timeout error?
                results[k] = {'status': 'RUNNING'}

            else:
                results[k] = r_1

        return results

    @login_required
    @check_proxies_blueprint.route("/<string:uuid>/start", methods=['GET'])
    def start_check(uuid):

        if not datastore.proxy_list:
            return

        if not checks_in_progress.get(uuid):
            checks_in_progress[uuid] = {}

        for k, v in datastore.proxy_list.items():
            if not checks_in_progress[uuid].get(k):
                checks_in_progress[uuid][k] = long_task(x=1, uuid=uuid, preferred_proxy=k)

        # Return dict of proxy labels and some status
        # return redirect(url_for("index", uuid=uuid))
        import time
        return str(time.time())

    return check_proxies_blueprint
