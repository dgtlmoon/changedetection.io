"""
site_inventory_diff — package metadata + custom Watch class exposing
inventory-specific notification tokens.

The processor_weight / list_badge_text / capability flags live on the
processor module itself; this file only re-exports the Watch class so
``get_custom_watch_obj_for_processor()`` can find it.
"""

from __future__ import annotations

import json
import os
from typing import Iterable, Optional

from loguru import logger

from changedetectionio.model.Watch import model as BaseWatch


# Processor capabilities — checked at form-render time by edit.html to decide
# which tabs to show. Mirror the flags in processor.py so the edit UI doesn't
# expose options that won't apply (e.g. visual selector).
supports_visual_selector = False
supports_browser_steps = False
supports_text_filters_and_triggers = True
supports_text_filters_and_triggers_elements = False
supports_request_type = True


CONFIG_FILENAME = "site_inventory_diff.json"


def _read_history_lines(watch: "Watch", timestamp: Optional[str]) -> list[str]:
    """Return body URLs (non-comment lines) from a watch history snapshot."""
    if not timestamp:
        return []
    snap = watch.get_history_snapshot(timestamp=timestamp)
    if not snap:
        return []
    urls: list[str] = []
    for line in snap.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


class Watch(BaseWatch):
    """Watch subclass for the site_inventory_diff processor.

    Adds:

    * ``{{new_urls}}`` / ``{{removed_urls}}`` / ``{{url_count}}`` notification
      tokens computed from the current and previous history snapshots.
    * ``{{inventory_warnings}}`` carrying cap/budget messages from the last
      check (useful in notifications for a sanity ping).
    """

    # --- Processor-specific helpers used by the dashboard blueprint -----

    def get_site_inventory_meta(self) -> dict:
        """Return the processor's persisted meta (mode, url_count, warnings).

        Returns an empty dict on first-run / missing-config — callers should
        handle that.
        """
        data_dir = self.data_dir
        if not data_dir:
            return {}
        path = os.path.join(data_dir, CONFIG_FILENAME)
        if not os.path.isfile(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as exc:
            logger.debug(f"site_inventory_diff: meta read failed {path!r}: {exc!r}")
            return {}
        return data.get("site_inventory_diff_last") or {}

    def compute_url_delta(
        self, newer_timestamp: Optional[str], older_timestamp: Optional[str]
    ) -> tuple[list[str], list[str]]:
        """Return ``(added, removed)`` between two history snapshots.

        If either snapshot is missing, returns an empty tuple-of-lists.
        """
        newer = set(_read_history_lines(self, newer_timestamp))
        older = set(_read_history_lines(self, older_timestamp))
        if not newer and not older:
            return [], []
        added = sorted(newer - older)
        removed = sorted(older - newer)
        return added, removed

    def get_latest_two_history_keys(self) -> tuple[Optional[str], Optional[str]]:
        history = self.history or {}
        if not history:
            return None, None
        keys = sorted(history.keys(), key=lambda k: int(k))
        if len(keys) == 1:
            return keys[-1], None
        return keys[-1], keys[-2]

    # --- Notification tokens --------------------------------------------

    def extra_notification_token_values(self) -> dict:
        values = super().extra_notification_token_values()

        newest, previous = self.get_latest_two_history_keys()
        added, removed = self.compute_url_delta(newest, previous)

        values["new_urls"] = "\n".join(added)
        values["removed_urls"] = "\n".join(removed)
        values["new_urls_count"] = len(added)
        values["removed_urls_count"] = len(removed)

        meta = self.get_site_inventory_meta()
        values["url_count"] = meta.get("url_count", 0)
        values["inventory_mode"] = meta.get("mode", "")
        values["inventory_warnings"] = "\n".join(meta.get("warnings", []) or [])

        return values

    def extra_notification_token_placeholder_info(self) -> list[tuple[str, str]]:
        values = super().extra_notification_token_placeholder_info()
        values.extend(
            [
                ("new_urls", "URLs added since the previous check (one per line)"),
                ("removed_urls", "URLs removed since the previous check (one per line)"),
                ("new_urls_count", "Number of URLs added since the previous check"),
                ("removed_urls_count", "Number of URLs removed since the previous check"),
                ("url_count", "Total URLs discovered in the latest inventory"),
                ("inventory_mode", "Detection mode used (sitemap, html, crawl …)"),
                ("inventory_warnings", "Warnings emitted by the last inventory run"),
            ]
        )
        return values
