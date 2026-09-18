"""
Regression tests for issue #3490 - "'restock' is undefined".

A `{{ restock.price }}` token is accepted in a per-watch notification body (restock
watches inject the value via processors/restock_diff extra_notification_token_values()),
but the same token in a system-wide / non-restock context had no default. That made it:

  1. crash rendering at send time for a non-restock watch (UndefinedError), and
  2. fail save-time validation of a system-wide notification body (ValidationError),

because `restock` was absent from NotificationContextData's default token set.

These tests exercise the real send-time (jinja2_custom.render) and save-time
(ValidateJinja2Template) code paths. They fail on a tree without the safe-empty
default and pass with it.
"""
from changedetectionio.notification_service import NotificationContextData


def test_restock_token_present_in_default_context():
    assert 'restock' in NotificationContextData()


def test_restock_token_renders_safely_for_non_restock_watch():
    """Send time: a non-restock watch must not crash on {{ restock.price }}."""
    from changedetectionio.jinja2_custom import render as jinja_render

    ctx = NotificationContextData()  # a plain, non-restock watch context
    rendered = jinja_render(template_str="Price is {{ restock.price }}", **ctx)
    # The undefined price renders as empty rather than raising UndefinedError.
    assert rendered == "Price is "


def test_restock_token_validates_in_system_settings():
    """Save time: a system-wide body using {{ restock.price }} must validate."""
    from changedetectionio.forms import ValidateJinja2Template

    class _Field:
        def __init__(self, data):
            self.data = data

    # Raised ValidationError before the fix; must not raise now.
    ValidateJinja2Template()(None, _Field("Price is {{ restock.price }}"))
