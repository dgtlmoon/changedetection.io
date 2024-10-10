import importlib
from concurrent.futures import ThreadPoolExecutor

from changedetectionio.processors.text_json_diff.processor import FilterNotFoundInResponse
from changedetectionio.store import ChangeDetectionStore

from functools import wraps

from flask import Blueprint
from flask_login import login_required

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
        from changedetectionio.content_fetchers import exceptions as content_fetcher_exceptions
        from changedetectionio.safe_jinja import render as jinja_render

        status = {'status': '', 'length': 0, 'text': ''}

        contents = ''
        now = time.time()
        try:
            processor_module = importlib.import_module("changedetectionio.processors.text_json_diff.processor")
            update_handler = processor_module.perform_site_check(datastore=datastore,
                                                                 watch_uuid=uuid
                                                                 )

            update_handler.call_browser(preferred_proxy_id=preferred_proxy)
        # title, size is len contents not len xfer
        except content_fetcher_exceptions.Non200ErrorCodeReceived as e:
            if e.status_code == 404:
                status.update({'status': 'OK', 'length': len(contents), 'text': f"OK but 404 (page not found)"})
            elif e.status_code == 403 or e.status_code == 401:
                status.update({'status': 'ERROR', 'length': len(contents), 'text': f"{e.status_code} - Access denied"})
            else:
                status.update({'status': 'ERROR', 'length': len(contents), 'text': f"Status code: {e.status_code}"})
        except FilterNotFoundInResponse:
            status.update({'status': 'OK', 'length': len(contents), 'text': f"OK but CSS/xPath filter not found (page changed layout?)"})
        except content_fetcher_exceptions.EmptyReply as e:
            if e.status_code == 403 or e.status_code == 401:
                status.update({'status': 'ERROR OTHER', 'length': len(contents), 'text': f"Got empty reply with code {e.status_code} - Access denied"})
            else:
                status.update({'status': 'ERROR OTHER', 'length': len(contents) if contents else 0, 'text': f"Empty reply with code {e.status_code}, needs chrome?"})
        except content_fetcher_exceptions.ReplyWithContentButNoText as e:
            txt = f"Got reply but with no content - Status code {e.status_code} - It's possible that the filters were found, but contained no usable text (or contained only an image)."
            status.update({'status': 'ERROR', 'text': txt})
        except Exception as e:
            status.update({'status': 'ERROR OTHER', 'length': len(contents) if contents else 0, 'text': 'Error: '+type(e).__name__+str(e)})
        else:
            status.update({'status': 'OK', 'length': len(contents), 'text': ''})

        if status.get('text'):
            # parse 'text' as text for safety
            v = {'text': status['text']}
            status['text'] = jinja_render(template_str='{{text|e}}', **v)

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

        if checks_in_progress.get(uuid):
            state = _recalc_check_status(uuid=uuid)
            for proxy_key, v in state.items():
                if v.get('status') == 'RUNNING':
                    return state
        else:
            checks_in_progress[uuid] = {}

        for k, v in datastore.proxy_list.items():
            if not checks_in_progress[uuid].get(k):
                checks_in_progress[uuid][k] = long_task(uuid=uuid, preferred_proxy=k)

        results = _recalc_check_status(uuid=uuid)
        return results

    return check_proxies_blueprint
