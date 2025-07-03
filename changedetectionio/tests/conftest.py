#!/usr/bin/env python3
import psutil
import time
from threading import Thread

import pytest
from changedetectionio import changedetection_app
from changedetectionio import store
import os
import sys
from loguru import logger

from changedetectionio.tests.util import live_server_setup, new_live_server_setup

# https://github.com/pallets/flask/blob/1.1.2/examples/tutorial/tests/test_auth.py
# Much better boilerplate than the docs
# https://www.python-boilerplate.com/py3+flask+pytest/

global app

# https://loguru.readthedocs.io/en/latest/resources/migration.html#replacing-caplog-fixture-from-pytest-library
# Show loguru logs only if CICD pytest fails.
from loguru import logger
@pytest.fixture
def reportlog(pytestconfig):
    logging_plugin = pytestconfig.pluginmanager.getplugin("logging-plugin")
    handler_id = logger.add(logging_plugin.report_handler, format="{message}")
    yield
    logger.remove(handler_id)


def track_memory(memory_usage, ):
    process = psutil.Process(os.getpid())
    while not memory_usage["stop"]:
        current_rss = process.memory_info().rss
        memory_usage["peak"] = max(memory_usage["peak"], current_rss)
        time.sleep(0.01)  # Adjust the sleep time as needed

@pytest.fixture(scope='function')
def measure_memory_usage(request):
    memory_usage = {"peak": 0, "stop": False}
    tracker_thread = Thread(target=track_memory, args=(memory_usage,))
    tracker_thread.start()

    yield

    memory_usage["stop"] = True
    tracker_thread.join()

    # Note: ru_maxrss is in kilobytes on Unix-based systems
    max_memory_used = memory_usage["peak"] / 1024  # Convert to MB
    s = f"Peak memory used by the test {request.node.fspath} - '{request.node.name}': {max_memory_used:.2f} MB"
    logger.debug(s)

    with open("test-memory.log", 'a') as f:
        f.write(f"{s}\n")

    # Assert that the memory usage is less than 200MB
#    assert max_memory_used < 150, f"Memory usage exceeded 200MB: {max_memory_used:.2f} MB"


def cleanup(datastore_path):
    import glob
    # Unlink test output files

    for g in ["*.txt", "*.json", "*.pdf"]:
        files = glob.glob(os.path.join(datastore_path, g))
        for f in files:
            if 'proxies.json' in f:
                # Usually mounted by docker container during test time
                continue
            if os.path.isfile(f):
                os.unlink(f)

@pytest.fixture(scope='function', autouse=True)
def prepare_test_function(live_server):

    routes = [rule.rule for rule in live_server.app.url_map.iter_rules()]
    if '/test-random-content-endpoint' not in routes:
        logger.debug("Setting up test URL routes")
        new_live_server_setup(live_server)


    yield
    # Then cleanup/shutdown
    live_server.app.config['DATASTORE'].data['watching']={}
    time.sleep(0.3)
    live_server.app.config['DATASTORE'].data['watching']={}


@pytest.fixture(scope='session')
def app(request):
    """Create application for the tests."""
    datastore_path = "./test-datastore"

    # So they don't delay in fetching
    os.environ["MINIMUM_SECONDS_RECHECK_TIME"] = "0"
    try:
        os.mkdir(datastore_path)
    except FileExistsError:
        pass

    cleanup(datastore_path)

    app_config = {'datastore_path': datastore_path, 'disable_checkver' : True}
    cleanup(app_config['datastore_path'])

    logger_level = 'TRACE'

    logger.remove()
    log_level_for_stdout = { 'DEBUG', 'SUCCESS' }
    logger.configure(handlers=[
        {"sink": sys.stdout, "level": logger_level,
         "filter" : lambda record: record['level'].name in log_level_for_stdout},
        {"sink": sys.stderr, "level": logger_level,
         "filter": lambda record: record['level'].name not in log_level_for_stdout},
        ])

    datastore = store.ChangeDetectionStore(datastore_path=app_config['datastore_path'], include_default_watches=False)
    app = changedetection_app(app_config, datastore)

    # Disable CSRF while running tests
    app.config['WTF_CSRF_ENABLED'] = False
    app.config['STOP_THREADS'] = True

    def teardown():
        # Stop all threads and services
        datastore.stop_thread = True
        app.config.exit.set()
        
        # Shutdown workers gracefully before loguru cleanup
        try:
            from changedetectionio import worker_handler
            worker_handler.shutdown_workers()
        except Exception:
            pass
            
        # Stop socket server threads
        try:
            from changedetectionio.flask_app import socketio_server
            if socketio_server and hasattr(socketio_server, 'shutdown'):
                socketio_server.shutdown()
        except Exception:
            pass
        
        # Give threads a moment to finish their shutdown
        import time
        time.sleep(0.1)
        
        # Remove all loguru handlers to prevent "closed file" errors
        logger.remove()
        
        # Cleanup files
        cleanup(app_config['datastore_path'])

       
    request.addfinalizer(teardown)
    yield app
