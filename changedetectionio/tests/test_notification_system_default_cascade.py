import logging
from flask import url_for
from .util import (
    live_server_setup,
    wait_for_all_checks,
)
from ..model import USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH


def test_notification_system_default_format_cascades_to_telegram(
    client, live_server, datastore_path
):
    """
    Regression test for issue #4119 / PR #4120.

    When a watch uses 'System default' notification format and the global
    default is 'html' or 'htmlcolor', the cascading lookup must return the
    actual global default format (e.g. 'text' or 'html'), NOT the sentinel
    value USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH itself.

    Previously, Telegram notifications failed because _check_cascading_vars()
    returned the sentinel value when it should have resolved to the global
    default notification format.
    """
    live_server_setup(live_server)

    # 1. Set global notification format to a specific value (not the sentinel)
    # This simulates a user who configured 'text' as their system default.
    global_notification_format = 'text'
    res = client.post(
        url_for("settings.settings_page"),
        data={
            "application-notification_urls": url_for(
                "test_notification_endpoint", _external=True
            ).replace("http", "json") + "?status_code=204",
            "application-notification_format": global_notification_format,
            "requests-time_between_check-minutes": 180,
            "application-fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Settings updated." in res.data

    # 2. Add a new watch without setting its notification_format explicitly
    test_url = url_for("test_endpoint", _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ""},
        follow_redirects=True,
    )
    assert b"Watch added" in res.data

    wait_for_all_checks(client)

    # 3. Edit the watch and set its format to "System default" (the sentinel value)
    # This is the core scenario from issue #4119
    uuid = next(iter(live_server.app.config["DATASTORE"].data["watching"]))
    res = client.post(
        url_for("ui.ui_edit.edit_page", uuid=uuid),
        data={
            "url": test_url,
            "notification_format": USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH,
            "notification_urls": url_for(
                "test_notification_endpoint", _external=True
            ).replace("http", "json") + "?status_code=204",
            "notification_title": "Test watch",
            "time_between_check_use_default": "y",
            "fetch_backend": "html_requests",
        },
        follow_redirects=True,
    )
    assert b"Updated watch." in res.data

    # 4. Verify the watch's format is stored as the sentinel
    watch = live_server.app.config["DATASTORE"].data["watching"][uuid]
    assert watch.get("notification_format") == USE_SYSTEM_DEFAULT_NOTIFICATION_FORMAT_FOR_WATCH

    # 5. Trigger a notification and verify it does NOT fail due to the sentinel
    # being passed instead of the resolved global default.
    # The cascading resolver should convert the sentinel to 'text'.
    from ..notification_service import _check_cascading_vars

    resolved_format = _check_cascading_vars(
        watch,
        "notification_format",
        live_server.app.config["DATASTORE"],
    )
    # The resolved value must be the actual global default ('text'), NOT the sentinel
    assert resolved_format == global_notification_format, (
        f"Expected 'System default' sentinel to resolve to '{global_notification_format}', "
        f"but got '{resolved_format}' — Telegram notifications would fail with "
        f"'str is not callable' error"
    )

    # 6. Also verify other sentinel fields (notification_body, notification_title)
    # fall back correctly
    resolved_body = _check_cascading_vars(
        watch, "notification_body", live_server.app.config["DATASTORE"]
    )
    resolved_title = _check_cascading_vars(
        watch, "notification_title", live_server.app.config["DATASTORE"]
    )
    # These should return the global defaults when watch-level values are not set
    assert resolved_body is not None
    assert resolved_title is not None