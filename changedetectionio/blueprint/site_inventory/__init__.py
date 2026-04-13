"""
Blueprint: site_inventory  (v3 dashboard + CSV export)

Mounts at ``/site-inventory`` and exposes three views:

* ``/``                 — global dashboard (aggregate new/removed this week)
* ``/tag/<tag_uuid>``   — per-tag rollup
* ``/watch/<uuid>.csv`` — CSV export of the current URL inventory

All routes are gauged by the global login decorator (``@login_required``) so
they inherit the existing password protection.
"""

from __future__ import annotations

import csv
import io
import time
from collections import Counter
from typing import Optional

from flask import Blueprint, Response, abort, render_template, url_for
from flask_login import login_required
from loguru import logger

from changedetectionio.store import ChangeDetectionStore


PROCESSOR_NAME = "site_inventory_diff"
# "Recent" window for the dashboard, in seconds. Keep this server-side so it's
# trivial to tune without a schema change.
RECENT_WINDOW_SECONDS = 7 * 24 * 3600


def _read_snapshot_urls(watch, timestamp: Optional[str]) -> list[str]:
    """Read a snapshot for an inventory watch and return body URL lines."""
    if not timestamp:
        return []
    try:
        snap = watch.get_history_snapshot(timestamp=timestamp)
    except Exception as exc:
        logger.debug(f"site_inventory: snapshot read failed: {exc!r}")
        return []
    if not snap:
        return []
    out: list[str] = []
    for line in snap.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def _latest_two(watch) -> tuple[Optional[str], Optional[str]]:
    history = watch.history or {}
    if not history:
        return None, None
    keys = sorted(history.keys(), key=lambda k: int(k))
    if len(keys) == 1:
        return keys[-1], None
    return keys[-1], keys[-2]


def _recent_delta_for_watch(watch, cutoff_unix: int) -> dict:
    """Aggregate added/removed URL counts within the recent window.

    We walk the history from newest to oldest, stop when we cross the cutoff,
    and union deltas so the dashboard reflects 'what happened this week'.
    """
    history = watch.history or {}
    if not history:
        return {"added": set(), "removed": set(), "latest_ts": None}

    keys = sorted(history.keys(), key=lambda k: int(k), reverse=True)
    added: set[str] = set()
    removed: set[str] = set()
    latest_ts = keys[0]

    # Walk pairs (k[i], k[i+1]) == (newer, older) from newest to oldest.
    for newer, older in zip(keys, keys[1:]):
        if int(newer) < cutoff_unix:
            break
        newer_set = set(_read_snapshot_urls(watch, newer))
        older_set = set(_read_snapshot_urls(watch, older))
        added |= newer_set - older_set
        removed |= older_set - newer_set

    return {"added": added, "removed": removed, "latest_ts": latest_ts}


def _inventory_watches(datastore: ChangeDetectionStore):
    """Yield ``(uuid, watch)`` for every watch using the inventory processor."""
    for uuid, watch in datastore.data.get("watching", {}).items():
        if watch.get("processor") == PROCESSOR_NAME:
            yield uuid, watch


def construct_blueprint(datastore: ChangeDetectionStore) -> Blueprint:
    bp = Blueprint(
        "site_inventory",
        __name__,
        template_folder="templates",
    )

    @bp.route("/", methods=["GET"], endpoint="dashboard")
    @login_required
    def dashboard():
        cutoff = int(time.time()) - RECENT_WINDOW_SECONDS

        rows = []
        total_added = 0
        total_removed = 0
        total_urls = 0
        tag_counter: Counter = Counter()

        for uuid, watch in _inventory_watches(datastore):
            delta = _recent_delta_for_watch(watch, cutoff)
            meta = {}
            try:
                meta = watch.get_site_inventory_meta()  # type: ignore[attr-defined]
            except AttributeError:
                # Happens if this watch's processor was switched away and the
                # custom Watch class is no longer in use — fall back gracefully.
                pass

            added_count = len(delta["added"])
            removed_count = len(delta["removed"])
            url_count = int(meta.get("url_count", 0) or 0)

            total_added += added_count
            total_removed += removed_count
            total_urls += url_count

            tags_for_watch = datastore.get_all_tags_for_watch(uuid) or {}
            for t_uuid in tags_for_watch:
                tag_counter[t_uuid] += added_count

            rows.append(
                {
                    "uuid": uuid,
                    "label": watch.label,
                    "url": watch.get("url"),
                    "mode": meta.get("mode", ""),
                    "url_count": url_count,
                    "added_recent": added_count,
                    "removed_recent": removed_count,
                    "warnings": meta.get("warnings", []) or [],
                    "latest_ts": delta["latest_ts"],
                    "tags": list(tags_for_watch.items()),
                }
            )

        rows.sort(key=lambda r: (-r["added_recent"], -r["removed_recent"]))

        return render_template(
            "inventory_dashboard.html",
            rows=rows,
            total_added=total_added,
            total_removed=total_removed,
            total_urls=total_urls,
            watch_count=len(rows),
            tag_counter=tag_counter,
            window_days=RECENT_WINDOW_SECONDS // 86400,
            datastore=datastore,
        )

    @bp.route("/tag/<tag_uuid>", methods=["GET"], endpoint="tag_report")
    @login_required
    def tag_report(tag_uuid: str):
        tag = datastore.data["settings"]["application"]["tags"].get(tag_uuid)
        if not tag:
            abort(404)

        cutoff = int(time.time()) - RECENT_WINDOW_SECONDS

        rows = []
        union_added: set[str] = set()
        union_removed: set[str] = set()

        for uuid, watch in _inventory_watches(datastore):
            if tag_uuid not in (watch.get("tags") or []):
                continue
            delta = _recent_delta_for_watch(watch, cutoff)
            union_added |= delta["added"]
            union_removed |= delta["removed"]
            rows.append(
                {
                    "uuid": uuid,
                    "label": watch.label,
                    "url": watch.get("url"),
                    "added_recent": sorted(delta["added"]),
                    "removed_recent": sorted(delta["removed"]),
                    "latest_ts": delta["latest_ts"],
                }
            )

        rows.sort(key=lambda r: (-len(r["added_recent"]), -len(r["removed_recent"])))

        return render_template(
            "inventory_tag_report.html",
            tag=tag,
            tag_uuid=tag_uuid,
            rows=rows,
            union_added=sorted(union_added),
            union_removed=sorted(union_removed),
            window_days=RECENT_WINDOW_SECONDS // 86400,
        )

    @bp.route("/watch/<uuid>.csv", methods=["GET"], endpoint="csv_export")
    @login_required
    def csv_export(uuid: str):
        watch = datastore.data.get("watching", {}).get(uuid)
        if not watch or watch.get("processor") != PROCESSOR_NAME:
            abort(404)

        newest, previous = _latest_two(watch)
        latest = set(_read_snapshot_urls(watch, newest))
        prev = set(_read_snapshot_urls(watch, previous))

        # Status column lets ops pipe this into spreadsheets easily.
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["url", "status", "latest_snapshot_unix", "previous_snapshot_unix"])
        for url in sorted(latest | prev):
            if url in latest and url in prev:
                status = "present"
            elif url in latest:
                status = "added"
            else:
                status = "removed"
            writer.writerow([url, status, newest or "", previous or ""])

        fname = f"inventory-{uuid}.csv"
        return Response(
            buf.getvalue(),
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="{fname}"',
                "Cache-Control": "no-store",
            },
        )

    return bp
