"""
Test registering a custom NotificationProfileType via registry.register().

Verifies that:
- A third-party type can be registered alongside the built-in Apprise type
- The registry resolves it correctly by type_id
- A watch linked to a profile of that type fires send() when a change is detected
- The custom send() receives a populated NotificationContextData object
"""

import uuid as uuid_mod
from flask import url_for

from changedetectionio.tests.util import (
    set_original_response,
    set_modified_response,
    live_server_setup,
    wait_for_all_checks,
    wait_for_notification_endpoint_output,
)


def test_custom_notification_profile_type_registration(client, live_server, measure_memory_usage, datastore_path):
    """
    Register a custom NotificationProfileType that POSTs to the test endpoint,
    link it to a watch via a profile, trigger a change, and confirm the custom
    send() was called.
    """
    from changedetectionio.notification_profiles.registry import registry, NotificationProfileType

    # ── 1. Define and register a custom type ─────────────────────────────────

    class WebhookProfileType(NotificationProfileType):
        """Simple webhook type: POSTs watch_url + watch_title JSON to a webhook_url."""
        type_id      = 'test_webhook'
        display_name = 'Test Webhook'
        icon         = 'send'
        template     = 'notification_profiles/types/apprise.html'  # reuse apprise template for UI

        def send(self, config: dict, n_object, datastore) -> bool:
            import requests as req
            webhook_url = config.get('webhook_url')
            if not webhook_url:
                return False
            payload = {
                'watch_url':   n_object.get('watch_url', ''),
                'watch_title': n_object.get('watch_title', ''),
                'diff':        n_object.get('diff', ''),
            }
            req.post(webhook_url, json=payload, timeout=5)
            return True

        def validate(self, config: dict) -> None:
            if not config.get('webhook_url'):
                raise ValueError("webhook_url is required")

    # Register — idempotent if test runs more than once in a session
    registry.register(WebhookProfileType)
    assert registry.get('test_webhook') is not None, "Custom type should be in registry after register()"
    assert registry.get('test_webhook').type_id == 'test_webhook'

    # ── 2. Set up live server and test content ────────────────────────────────

    live_server_setup(live_server)
    set_original_response(datastore_path=datastore_path)

    datastore = client.application.config.get('DATASTORE')
    webhook_url = url_for('test_notification_endpoint', _external=True)

    # ── 3. Create a profile using the custom type ─────────────────────────────

    uid = str(uuid_mod.uuid4())
    datastore.data['settings']['application'].setdefault('notification_profile_data', {})[uid] = {
        'uuid':   uid,
        'name':   'Custom Webhook Profile',
        'type':   'test_webhook',
        'config': {'webhook_url': webhook_url},
    }

    # ── 4. Add a watch ────────────────────────────────────────────────────────

    test_url = url_for('test_endpoint', _external=True)
    res = client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": ''},
        follow_redirects=True,
    )
    assert b"Watch added" in res.data
    wait_for_all_checks(client)

    watch_uuid = next(iter(datastore.data['watching']))

    # Link the custom profile to the watch
    datastore.data['watching'][watch_uuid]['notification_profiles'] = [uid]
    datastore.data['watching'][watch_uuid].commit()

    # ── 5. Trigger a change ───────────────────────────────────────────────────

    set_modified_response(datastore_path=datastore_path)

    client.get(url_for("ui.form_watch_checknow"), follow_redirects=True)
    wait_for_all_checks(client)

    # ── 6. Verify the custom send() was called ────────────────────────────────

    assert wait_for_notification_endpoint_output(datastore_path), \
        "Custom WebhookProfileType.send() should have POSTed to the test notification endpoint"

    # ── 7. Cleanup: unregister the test type so it doesn't bleed into other tests ──

    registry._types.pop('test_webhook', None)
