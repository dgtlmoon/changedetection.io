from concurrent.futures import ThreadPoolExecutor

from functools import wraps

from flask import Blueprint
from flask_login import login_required

from changedetectionio.processors import text_json_diff
from changedetectionio.store import ChangeDetectionStore


STATUS_CHECKING = 0
STATUS_FAILED = 1
STATUS_OK = 2
THREADPOOL_MAX_WORKERS = 3
_DEFAULT_POOL = ThreadPoolExecutor(max_workers=THREADPOOL_MAX_WORKERS)


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
    def long_task(uuid, preferred_proxy):
        import time
        from changedetectionio import content_fetcher

        status = {'status': '', 'length': 0, 'text': ''}
        from jinja2 import Environment, BaseLoader

        contents = ''
        now = time.time()
        try:
            update_handler = text_json_diff.perform_site_check(datastore=datastore)
            changed_detected, update_obj, contents = update_handler.run(uuid, preferred_proxy=preferred_proxy, skip_when_checksum_same=False)
        # title, size is len contents not len xfer
        except content_fetcher.Non200ErrorCodeReceived as e:
            if e.status_code == 404:
                status.update({'status': 'OK', 'length': len(contents), 'text': f"OK but 404 (page not found)"})
            elif e.status_code == 403:
                status.update({'status': 'ERROR', 'length': len(contents), 'text': f"403 - Access denied"})
            else:
                status.update({'status': 'ERROR', 'length': len(contents), 'text': f"Status code: {e.status_code}"})
        except text_json_diff.FilterNotFoundInResponse:
            status.update({'status': 'OK', 'length': len(contents), 'text': f"OK but CSS/xPath filter not found (page changed layout?)"})
        except content_fetcher.EmptyReply as e:
            status.update({'status': 'ERROR OTHER', 'length': len(contents) if contents else 0, 'text': "Empty reply, needs chrome?"})
        except Exception as e:
            status.update({'status': 'ERROR OTHER', 'length': len(contents) if contents else 0, 'text': 'Error: '+str(e)})
        else:
            status.update({'status': 'OK', 'length': len(contents), 'text': ''})

        if status.get('text'):
            status['text'] = Environment(loader=BaseLoader()).from_string('{{text|e}}').render({'text': status['text']})

        status['time'] = "{:.2f}s".format(time.time() - now)

        return status

    def _recalc_check_status(uuid):

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
    @check_proxies_blueprint.route("/<string:uuid>/status", methods=['GET'])
    def get_recheck_status(uuid):
        results = _recalc_check_status(uuid=uuid)
        return results

    @login_required
    @check_proxies_blueprint.route("/<string:uuid>/start", methods=['GET'])
    def start_check(uuid):

        if not datastore.proxy_list:
            return

        # @todo - Cancel any existing runs
        checks_in_progress[uuid] = {}

        for k, v in datastore.proxy_list.items():
            if not checks_in_progress[uuid].get(k):
                checks_in_progress[uuid][k] = long_task(uuid=uuid, preferred_proxy=k)

        results = _recalc_check_status(uuid=uuid)
        return results

    return check_proxies_blueprint
