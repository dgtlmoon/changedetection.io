"""
site_inventory_diff — package metadata + custom Watch class exposing
inventory-specific notification tokens.

The processor_weight / list_badge_text / capability flags live on the
processor module itself; this file only re-exports the Watch class so
``get_custom_watch_obj_for_processor()`` can find it.

This module also registers a ``ui_edit_stats_extras`` pluggy hookimpl that
injects an inventory-specific widget into the Stats tab on the edit page
when the watch is using this processor. The hook fires for every watch; we
return an empty string for non-inventory watches so we don't spam the tab.
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from typing import Iterable, Optional

from loguru import logger

from changedetectionio.model.Watch import model as BaseWatch
from changedetectionio.pluggy_interface import hookimpl, plugin_manager


# Processor capabilities — checked at form-render time by edit.html to decide
# which tabs to show. Mirror the flags in processor.py so the edit UI doesn't
# expose options that won't apply (e.g. visual selector). The text filters &
# triggers tab is intentionally hidden: the snapshot for this processor is a
# sorted URL list, not page text, so trigger_text / ignore_text would silently
# do nothing. URL-level filtering is exposed via the processor's own
# include_regex / exclude_regex / css_scope fields.
supports_visual_selector = False
supports_browser_steps = False
supports_text_filters_and_triggers = False
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


# ---------------------------------------------------------------------------
# Stats-tab widget (ui_edit_stats_extras pluggy hook)
#
# The edit.html Stats tab renders ``ui_edit_stats_extras|safe`` verbatim.
# This hookimpl returns inventory-specific HTML *only* for watches that use
# this processor, so the widget doesn't appear for text/restock/image watches.
# ---------------------------------------------------------------------------

# Hard cap on how many added/removed URLs we list inline. Everything else is
# still available via the CSV export link we render at the bottom of the widget.
_DELTA_DISPLAY_CAP = 25


def _fmt_unix(ts) -> str:
    """Return a human-ish UTC timestamp for a unix int, or '—'."""
    try:
        t = int(ts)
    except (TypeError, ValueError):
        return "\u2014"
    if t <= 0:
        return "\u2014"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(t))


def _render_stats_widget(watch: "Watch") -> str:
    """Build the inventory stats HTML fragment for a single watch.

    Kept pure (no flask imports) so it's trivially testable — the caller is
    responsible for deciding whether to render it at all.
    """
    meta = watch.get_site_inventory_meta()
    newest, previous = watch.get_latest_two_history_keys()
    added, removed = watch.compute_url_delta(newest, previous)

    mode = html.escape(str(meta.get("mode", "\u2014")))
    url_count = int(meta.get("url_count", 0) or 0)
    source_url = html.escape(str(meta.get("source_url", watch.get("url", ""))))
    generated_at = _fmt_unix(meta.get("generated_at_unix", 0))
    warnings = meta.get("warnings", []) or []

    added_shown = added[:_DELTA_DISPLAY_CAP]
    removed_shown = removed[:_DELTA_DISPLAY_CAP]
    added_overflow = max(0, len(added) - len(added_shown))
    removed_overflow = max(0, len(removed) - len(removed_shown))

    def _url_list(items: list[str]) -> str:
        if not items:
            return '<em style="opacity: 0.7;">none</em>'
        rows = "\n".join(
            f'<li><code>{html.escape(u)}</code></li>' for u in items
        )
        return f'<ul style="margin: 0.25rem 0 0.25rem 1.1rem; padding: 0;">{rows}</ul>'

    added_overflow_html = (
        f'<p style="opacity:.7; margin:0.25rem 0 0;">\u2026and {added_overflow} more (see CSV)</p>'
        if added_overflow else ""
    )
    removed_overflow_html = (
        f'<p style="opacity:.7; margin:0.25rem 0 0;">\u2026and {removed_overflow} more (see CSV)</p>'
        if removed_overflow else ""
    )
    delta_open = "open" if (added or removed) else ""

    # Warnings panel — emitted only when present so the widget stays tight.
    warnings_html = ""
    if warnings:
        items = "\n".join(f"<li>{html.escape(str(w))}</li>" for w in warnings)
        warnings_html = (
            '<div class="inline-warning" style="margin-top: 0.75rem;">'
            f'<strong>Warnings from last run:</strong><ul style="margin:0.25rem 0 0 1rem;">{items}</ul>'
            "</div>"
        )

    # CSV + dashboard links — these URLs are stable so we can build them by
    # convention (the blueprint is mounted at /site-inventory). Avoids needing
    # a flask app context inside a pluggy hook.
    uuid = html.escape(str(watch.get("uuid", "")))
    csv_href = f"/site-inventory/watch/{uuid}.csv"
    dashboard_href = "/site-inventory/"

    return f"""
<div class="site-inventory-stats" style="margin-top: 1rem;">
  <h4 style="margin: 0 0 0.5rem;">Site URL inventory</h4>
  <table class="pure-table" style="width: 100%;">
    <tbody>
      <tr><td>Source</td><td><code>{source_url}</code></td></tr>
      <tr><td>Mode (last run)</td><td>{mode}</td></tr>
      <tr><td>URLs tracked</td><td>{url_count}</td></tr>
      <tr><td>Last generated</td><td>{generated_at}</td></tr>
      <tr><td>Latest delta</td>
          <td><span class="num-added">+{len(added)}</span>
              &nbsp;
              <span class="num-removed">-{len(removed)}</span></td></tr>
    </tbody>
  </table>

  <details style="margin-top: 0.75rem;" {delta_open}>
    <summary><strong>Added&nbsp;({len(added)}) &nbsp;/&nbsp; Removed&nbsp;({len(removed)})</strong></summary>
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; margin-top: 0.5rem;">
      <div>
        <div class="num-added"><strong>Added</strong></div>
        {_url_list(added_shown)}
        {added_overflow_html}
      </div>
      <div>
        <div class="num-removed"><strong>Removed</strong></div>
        {_url_list(removed_shown)}
        {removed_overflow_html}
      </div>
    </div>
  </details>

  {warnings_html}

  <p style="margin-top: 0.75rem;">
    <a href="{csv_href}" class="pure-button button-small">Download CSV</a>
    <a href="{dashboard_href}" class="pure-button button-small">Inventory dashboard</a>
  </p>
</div>
"""


@hookimpl
def ui_edit_stats_extras(watch):
    """Return the inventory widget for watches using ``site_inventory_diff``.

    For every other processor we return an empty string so the Stats tab is
    left untouched.
    """
    try:
        if watch.get("processor") != "site_inventory_diff":
            return ""
        # Defensive: when the watch was just switched to this processor but
        # hasn't been re-hydrated as our custom Watch subclass yet, the
        # helper methods below won't exist. Fall back gracefully.
        if not hasattr(watch, "get_site_inventory_meta"):
            return ""
        return _render_stats_widget(watch)
    except Exception as exc:
        # Never break the edit page because of a widget render error.
        logger.warning(f"site_inventory_diff stats widget failed: {exc!r}")
        return ""


# Register this module itself as a pluggy plugin so the hookimpl above is
# actually collected. The module is imported during processor discovery via
# ``find_processors()``, so by the time pluggy's UI hook fires we're
# guaranteed to be registered. Guarded against double-registration (the
# package may be re-imported by test harnesses).
try:
    _plugin_name = "site_inventory_diff_stats"
    if not plugin_manager.is_registered(sys.modules[__name__]) and not plugin_manager.has_plugin(_plugin_name):
        plugin_manager.register(sys.modules[__name__], _plugin_name)
except Exception as exc:
    logger.warning(
        f"site_inventory_diff: failed to register stats hookimpl: {exc!r}"
    )
