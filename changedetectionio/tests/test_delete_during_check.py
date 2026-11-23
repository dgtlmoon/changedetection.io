import time

from flask import url_for

from changedetectionio import worker_pool
from changedetectionio.tests.util import delete_all_watches, set_original_response, wait_for_all_checks


def _wait_until(condition, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def test_delete_watch_while_it_is_being_checked(client, live_server, measure_memory_usage, datastore_path):
    """Deleting a watch stops the check that is running for it, and checks carry on afterwards."""
    set_original_response(datastore_path=datastore_path)
    datastore = client.application.config.get('DATASTORE')
    workers_before = worker_pool.get_worker_count()
    assert workers_before, "Needs at least one worker"

    slow_url = url_for('test_endpoint', _external=True) + "?delay=6"
    uuid = datastore.add_watch(url=slow_url, extras={'processor': 'restock_diff'})
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    assert _wait_until(lambda: worker_pool.is_watch_running(uuid)), "The slow check should have started"
    time.sleep(1)  # Let it get into the fetch

    started = time.time()
    res = client.post(url_for("ui.form_delete", uuid=uuid), follow_redirects=True)
    assert res.status_code == 200
    assert uuid not in datastore.data['watching']
    assert not worker_pool.is_watch_running(uuid), "The check should be stopped with the delete"
    assert time.time() - started < 4, "The delete should not wait for the slow fetch"
    assert worker_pool.get_worker_count() == workers_before, "The stopped worker should be replaced"

    # The replacement worker picks up the next check
    uuid2 = datastore.add_watch(url=url_for('test_endpoint', _external=True))
    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)
    assert datastore.data['watching'][uuid2].get('last_checked'), "Checks should still run after the delete"
    assert not datastore.data['watching'][uuid2].get('last_error')

    delete_all_watches(client)


def test_extra_watch_config_of_deleted_watch(client, live_server, measure_memory_usage, datastore_path):
    """A processor that is still running when its watch is deleted reads no config and saves none."""
    from changedetectionio.processors.restock_diff.processor import perform_site_check

    datastore = client.application.config.get('DATASTORE')
    datastore.data['settings']['application']['all_paused'] = True
    uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={'paused': True})
    handler = perform_site_check(datastore=datastore, watch_uuid=uuid)

    datastore.delete(uuid)

    assert handler.get_extra_watch_config('restock_diff.json') == {}
    handler.update_extra_watch_config('restock_diff.json', {'a': 1})

    datastore.data['settings']['application']['all_paused'] = False
    delete_all_watches(client)
