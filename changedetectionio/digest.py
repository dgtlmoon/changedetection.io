"""
Scheduled digest emails.

Wakes up every ~60s and, if:
  * settings.application.digest_enabled is True, AND
  * the current UTC hour == digest_hour_utc, AND
  * we haven't already sent a digest inside the current window
    (24h for 'daily', 7d for 'weekly'),
builds a summary of recent watch activity and pushes it through the existing
notification queue — reusing the notification pipeline (Apprise, template
rendering, etc.) so it supports every destination the rest of the app does
(email, Slack, Discord, Telegram, custom webhook …).

No external scheduler (cron / APScheduler) is required — this is a simple
daemon thread started alongside the watch-ticker thread.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from loguru import logger


_CHECK_INTERVAL_SEC = 60      # how often the digest loop wakes up
_MIN_WINDOW_DAILY = 23 * 3600  # never send twice within 23h for 'daily'
_MIN_WINDOW_WEEKLY = 6 * 86400  # never send twice within 6d for 'weekly'


def _default_body_template() -> str:
    """Jinja-ish f-string style template — we render with simple Python formatting
    to avoid pulling another Jinja env and to keep the digest body plaintext-safe
    for every Apprise destination."""
    return (
        "changedetection.io — {frequency} digest for {window_label}\n"
        "\n"
        "{summary_line}\n"
        "\n"
        "{changed_block}"
        "{unchanged_block}"
        "\n"
        "— Sent by changedetection.io at {now_utc} UTC"
    )


def _build_payload(datastore, *, now_epoch: int, frequency: str, include_unchanged: bool) -> dict:
    """
    Compose a notification-queue payload summarising watches whose newest history
    key falls inside the digest window.
    """
    window_sec = 86400 if frequency == "daily" else 7 * 86400
    window_start = now_epoch - window_sec

    changed = []
    unchanged = []
    errored = []

    for uuid, watch in datastore.data["watching"].items():
        try:
            newest = int(watch.newest_history_key or 0)
        except Exception:
            newest = 0

        title = watch.get("title") or watch.get("url") or uuid[:8]
        line = f"  • {title}  —  {watch.get('url', '')}"

        if watch.get("last_error"):
            errored.append(line + f"  [error: {watch.get('last_error')}]")
        elif newest and newest >= window_start:
            when = datetime.utcfromtimestamp(newest).strftime("%Y-%m-%d %H:%M UTC")
            changed.append(line + f"  [changed {when}]")
        else:
            unchanged.append(line)

    total_changed = len(changed)
    total_errored = len(errored)

    window_label = (
        f"last 24 hours" if frequency == "daily" else f"last 7 days"
    )
    summary_line = (
        f"{total_changed} watch(es) changed"
        + (f", {total_errored} with errors" if total_errored else "")
        + "."
    )

    changed_block = ""
    if changed:
        changed_block += "Changed:\n" + "\n".join(changed) + "\n"
    if errored:
        changed_block += "\nErrors:\n" + "\n".join(errored) + "\n"

    unchanged_block = ""
    if include_unchanged and unchanged:
        unchanged_block = "\nUnchanged:\n" + "\n".join(unchanged) + "\n"

    body = _default_body_template().format(
        frequency=frequency.capitalize(),
        window_label=window_label,
        summary_line=summary_line,
        changed_block=changed_block,
        unchanged_block=unchanged_block,
        now_utc=datetime.utcfromtimestamp(now_epoch).strftime("%Y-%m-%d %H:%M"),
    )
    title = f"changedetection.io — {frequency} digest ({total_changed} change(s))"

    app_settings = datastore.data["settings"]["application"]
    urls = list(app_settings.get("digest_notification_urls") or [])
    if not urls:
        # Fall back to the global default destinations.
        urls = list(app_settings.get("notification_urls") or [])

    return {
        "notification_title": title,
        "notification_body": body,
        "notification_format": "Text",
        "notification_urls": urls,
        "uuid": None,  # system-level notification
    }


def _should_send(app_settings: dict, *, now_epoch: int) -> bool:
    if not app_settings.get("digest_enabled"):
        return False
    if not (app_settings.get("digest_notification_urls") or app_settings.get("notification_urls")):
        # Nothing to send to.
        return False

    target_hour = int(app_settings.get("digest_hour_utc", 8))
    current_hour = datetime.now(timezone.utc).hour
    if current_hour != target_hour:
        return False

    last_sent = int(app_settings.get("digest_last_sent_epoch") or 0)
    frequency = app_settings.get("digest_frequency", "daily")
    min_window = _MIN_WINDOW_DAILY if frequency == "daily" else _MIN_WINDOW_WEEKLY
    if last_sent and (now_epoch - last_sent) < min_window:
        return False

    return True


def digest_email_scheduler(datastore, notification_q, *, app=None, check_interval_sec: int = _CHECK_INTERVAL_SEC):
    """
    Daemon loop. `app` is an optional Flask app — if supplied, the send is wrapped
    in an app context (required for url_for / blueprints in notification templates).
    """
    logger.info("digest_email_scheduler: started")
    while True:
        try:
            now_epoch = int(time.time())
            app_settings = datastore.data["settings"]["application"]
            if _should_send(app_settings, now_epoch=now_epoch):
                frequency = app_settings.get("digest_frequency", "daily")
                include_unchanged = bool(app_settings.get("digest_include_unchanged"))
                payload = _build_payload(
                    datastore,
                    now_epoch=now_epoch,
                    frequency=frequency,
                    include_unchanged=include_unchanged,
                )
                if payload["notification_urls"]:
                    logger.info(
                        f"digest_email_scheduler: queueing {frequency} digest to "
                        f"{len(payload['notification_urls'])} destination(s)"
                    )

                    def _push():
                        notification_q.put(payload)

                    if app is not None:
                        with app.app_context():
                            _push()
                    else:
                        _push()

                    # Record the send so we don't re-fire next minute in the same hour.
                    app_settings["digest_last_sent_epoch"] = now_epoch
                    try:
                        datastore.needs_write = True
                    except Exception:
                        pass
                else:
                    logger.warning(
                        "digest_email_scheduler: enabled but no notification_urls configured; skipping."
                    )
        except Exception as e:
            logger.exception(f"digest_email_scheduler: iteration failed: {e}")

        time.sleep(check_interval_sec)


def start_digest_thread(datastore, notification_q, *, app=None):
    """Spawn the digest scheduler as a daemon thread and return the Thread."""
    t = threading.Thread(
        target=digest_email_scheduler,
        kwargs={"datastore": datastore, "notification_q": notification_q, "app": app},
        daemon=True,
        name="digest-email-scheduler",
    )
    t.start()
    return t
