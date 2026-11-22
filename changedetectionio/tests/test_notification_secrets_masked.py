#!/usr/bin/env python3

"""A notification URL's password must not turn up in the log output or on the notification log page."""

import os
import time

from flask import url_for
from loguru import logger

from changedetectionio.notification import default_notification_body, default_notification_title
from .util import set_original_response, set_modified_response, wait_for_all_checks, wait_for_notification_endpoint_output

SECRET = 's3cretPassw0rd-9f1c'


def test_notification_url_password_is_not_logged(client, live_server, measure_memory_usage, datastore_path):
    set_original_response(datastore_path=datastore_path)
    if os.path.isfile(os.path.join(datastore_path, "notification.txt")):
        os.unlink(os.path.join(datastore_path, "notification.txt"))

    notification_url = url_for('test_notification_endpoint', _external=True).replace('http://', f'json://someuser:{SECRET}@') \
                       + "?status_code=204"

    log_lines = []
    sink = logger.add(lambda message: log_lines.append(str(message)), level='TRACE')
    try:
        datastore = client.application.config.get('DATASTORE')
        uuid = datastore.add_watch(url=url_for('test_endpoint', _external=True), extras={
            'notification_urls': [notification_url],
            'notification_title': default_notification_title,
            'notification_body': default_notification_body,
            'notification_format': 'text',
        })
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)

        set_modified_response(datastore_path=datastore_path)
        client.post(url_for("ui.form_watch_checknow"), follow_redirects=True)
        wait_for_all_checks(client)
        assert wait_for_notification_endpoint_output(datastore_path=datastore_path), "The notification was never sent"

        # The worker writes its line to the notification log after the send
        for _ in range(10):
            res = client.get(url_for("settings.notification_logs"))
            if b'SENDING' in res.data:
                break
            time.sleep(0.5)
    finally:
        logger.remove(sink)

    assert not datastore.data['watching'][uuid].get('last_notification_error')

    # It did get there with the password, the endpoint was given it as basic auth
    with open(os.path.join(datastore_path, "notification-headers.txt")) as f:
        assert 'Authorization: Basic' in f.read()

    assert b'SENDING' in res.data, "Expected the sent notification on the notification log page"
    # The rest of what was sent is still there to read
    assert b'ChangeDetection.io Notification - ' in res.data and b'someuser' in res.data
    assert SECRET.encode() not in res.data, "The notification log page shows the notification URL's password"

    assert any('start notifying' in line for line in log_lines), "Expected the send to be logged"
    leaked = [line for line in log_lines if SECRET in line]
    assert not leaked, f"The notification URL's password was logged: {leaked[:2]}"

    client.post(url_for("ui.form_delete", uuid="all"), follow_redirects=True)
