"""
site_inventory_diff — detect pages being added to or removed from a site.

The snapshot is just plain text: one canonical URL per line, sorted. The
existing text-diff pipeline therefore produces added/removed lists for free,
and downstream features (history, RSS, notification tokens, preview) all work
unchanged.

Three sources are supported:

``auto``          : sniff by content-type / URL suffix. Default.
``sitemap``       : treat the response as sitemap.xml (or a sitemap index).
``html``          : treat as an HTML listing page; extract ``<a href>``.
``crawl``         : bounded same-origin BFS crawl (v2 — runs a separate,
                    requests-only client and ignores the fetch_backend).

The processor honors the existing fetcher stack for the first three modes, so
Playwright/Selenium-rendered listing pages work fine. The crawl mode runs its
own HTTP client because it issues many requests and needs per-request
robots.txt + delay enforcement.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Optional

import requests
from loguru import logger

from changedetectionio.content_fetchers.exceptions import (
    checksumFromPreviousCheckWasTheSame,
)

from ..base import difference_detection_processor
from ..exceptions import ProcessorException
from . import extractors
from . import normalize


# Translatable strings — pybabel extraction marker.
def _(x):
    return x


name = _("Site URL inventory — detect new / removed pages")
description = _(
    "Track when pages are added to or removed from a site. Point at a "
    "sitemap.xml, a listing page, or let the bounded crawler walk the site."
)
del _

processor_weight = 2
list_badge_text = "Inventory"

# Processor capabilities — crawl mode does its own fetching so we don't
# advertise browser_steps / visual_selector. The text diff engine still runs
# the snapshot through the existing filter/trigger pipeline which is useful
# (e.g. ignore_text).
supports_visual_selector = False
supports_browser_steps = False
supports_text_filters_and_triggers = True
supports_text_filters_and_triggers_elements = False
supports_request_type = True


# JSON file we use to persist per-watch config (same pattern as restock_diff).
CONFIG_FILENAME = "site_inventory_diff.json"

# Maximum characters we'll store per snapshot. At ~80 chars/URL this is ~125k
# URLs which is well beyond any realistic single-watch target.
MAX_SNAPSHOT_BYTES = 10_000_000


def _default_config() -> dict:
    """Defaults applied when a watch has no persisted config yet. Kept here
    (not in forms.py) so programmatic callers / recipes can rely on them too.
    """
    return {
        "source_type": "auto",
        "css_scope": "",
        "same_origin_only": True,
        "strip_query_strings": True,
        "strip_tracking_params_always": True,
        "follow_sitemap_index": True,
        "include_regex": "",
        "exclude_regex": "",
        # Crawl-mode (v2) fields
        "crawl_max_pages": 100,
        "crawl_max_depth": 2,
        "crawl_delay_seconds": 1.0,
        "crawl_time_budget_seconds": 60.0,
        "crawl_respect_robots_txt": True,
    }


def _merge_config(stored: dict) -> dict:
    cfg = _default_config()
    cfg.update({k: v for k, v in (stored or {}).items() if v is not None})
    return cfg


def _regex_or_none(value: str):
    """Compile a regex from user config; treat blanks / bad regex as None and
    log — we never want a bad regex to crash the processor.
    """
    if not value:
        return None
    try:
        return re.compile(value)
    except re.error as exc:
        logger.warning(f"site_inventory_diff: invalid regex {value!r}: {exc!r}")
        return None


class perform_site_check(difference_detection_processor):
    """The one class the runner expects. Implements the abstract contract."""

    screenshot = None
    xpath_data = None

    # --- Utility helpers -------------------------------------------------

    def _load_config(self) -> dict:
        stored = self.get_extra_watch_config(CONFIG_FILENAME)
        return _merge_config(
            (stored or {}).get("site_inventory_diff") or stored or {}
        )

    def _save_inventory_meta(self, meta: dict) -> None:
        """Persist the latest metadata (url_count, mode used, warnings).

        Used by the v3 dashboard and by the notification-token layer via the
        custom Watch class in __init__.py.
        """
        self.update_extra_watch_config(
            CONFIG_FILENAME,
            {"site_inventory_diff_last": meta},
            merge=True,
        )

    def _fetch_child_sitemap(
        self, child_url: str, timeout: float = 30.0
    ) -> Optional[bytes]:
        """Fetch a child sitemap over plain HTTP.

        We intentionally use ``requests`` here rather than re-running the full
        fetcher — child sitemaps are always plain XML, and routing every child
        fetch back through Playwright would be absurd and slow.
        """
        try:
            resp = requests.get(
                child_url,
                headers={"User-Agent": "onChange-Inventory/1.0"},
                timeout=timeout,
                allow_redirects=True,
            )
            if 200 <= resp.status_code < 300:
                return resp.content
            logger.info(
                f"Child sitemap {child_url} returned HTTP {resp.status_code}"
            )
        except requests.RequestException as exc:
            logger.info(f"Child sitemap {child_url} fetch failed: {exc!r}")
        return None

    # --- Snapshot construction ------------------------------------------

    def _emit_snapshot(
        self,
        urls: list[str],
        *,
        source_url: str,
        mode: str,
        warnings: list[str],
    ) -> tuple[bytes, dict]:
        """Format the snapshot text and return ``(bytes, meta)``.

        A stable header is included so operators and downstream tooling can
        see what was fetched and when, but it uses ``#`` prefixes so the diff
        engine doesn't treat header changes as page changes.
        """
        generated_at = int(time.time())

        header_lines = [
            f"# onChange site URL inventory",
            f"# source: {source_url}",
            f"# mode: {mode}",
            f"# generated_at_unix: {generated_at}",
            f"# url_count: {len(urls)}",
        ]
        for w in warnings:
            header_lines.append(f"# warning: {w}")
        header_lines.append("#")  # blank separator

        body = "\n".join(urls)
        text = "\n".join(header_lines) + "\n" + body + ("\n" if body else "")

        if len(text.encode("utf-8", errors="replace")) > MAX_SNAPSHOT_BYTES:
            # Truncate if the response is absurdly large — better a partial
            # snapshot than a watch that crashes forever.
            logger.warning(
                f"site_inventory_diff: snapshot >{MAX_SNAPSHOT_BYTES} bytes; truncating"
            )
            text = text.encode("utf-8", errors="replace")[:MAX_SNAPSHOT_BYTES].decode(
                "utf-8", errors="ignore"
            )

        meta = {
            "url_count": len(urls),
            "mode": mode,
            "source_url": source_url,
            "warnings": warnings,
            "generated_at_unix": generated_at,
        }
        return text.encode("utf-8"), meta

    # --- Core logic -----------------------------------------------------

    def run_changedetection(self, watch, force_reprocess=False):
        if not watch:
            raise Exception("Watch no longer exists.")

        cfg = self._load_config()
        source_url = watch.link
        update_obj: dict = {
            "last_notification_error": False,
            "last_error": False,
        }

        # Skip rebuild if raw content is byte-for-byte identical AND watch
        # wasn't edited — identical to the pattern in restock_diff.
        # NOTE: crawl mode has no single raw content, so skip logic is limited
        # to source_type in (auto, sitemap, html).
        current_raw_document_checksum = self.get_raw_document_checksum()
        if (
            cfg["source_type"] != "crawl"
            and not force_reprocess
            and not watch.was_edited
            and self.last_raw_content_checksum
            and self.last_raw_content_checksum == current_raw_document_checksum
        ):
            raise checksumFromPreviousCheckWasTheSame()

        update_obj["content-type"] = self.fetcher.headers.get("Content-Type", "")
        update_obj["last_check_status"] = self.fetcher.get_last_status_code()
        self.update_last_raw_content_checksum(current_raw_document_checksum)

        warnings: list[str] = []

        # Dispatch by source_type
        source_type = cfg["source_type"]
        if source_type == "auto":
            source_type = extractors.sniff_source_type(
                content=self.fetcher.content or b"",
                content_type=update_obj["content-type"],
                url=source_url,
            )

        normalize_opts = {
            "strip_query": bool(cfg["strip_query_strings"]),
            "strip_tracking_params_always": bool(
                cfg["strip_tracking_params_always"]
            ),
        }

        raw_urls: list[str] = []
        actual_mode = source_type

        try:
            if source_type == "sitemap":
                raw_urls = extractors.extract_from_sitemap_xml(self.fetcher.content)
            elif source_type == "sitemap_index":
                if not cfg["follow_sitemap_index"]:
                    warnings.append(
                        "Sitemap index detected but follow_sitemap_index is off"
                    )
                    raw_urls = []
                else:
                    raw_urls, capped = extractors.extract_from_sitemap_index(
                        self.fetcher.content,
                        fetch_child=self._fetch_child_sitemap,
                    )
                    if capped:
                        warnings.append(
                            f"Sitemap index had more than "
                            f"{extractors.SITEMAP_INDEX_CHILD_CAP} children; "
                            f"truncated."
                        )
            elif source_type == "html":
                raw_urls = extractors.extract_from_html(
                    html=self.fetcher.content or "",
                    base_url=source_url,
                    css_scope=cfg["css_scope"] or None,
                )
            elif source_type == "crawl":
                # v2 — the fetcher already retrieved the seed; we ignore it and
                # run the bounded crawler directly. This keeps crawl UX simple
                # (only requires source URL) while still honoring the watch's
                # schedule / notification plumbing.
                from . import crawler

                cr = crawler.crawl(
                    seed_url=source_url,
                    max_pages=int(cfg["crawl_max_pages"] or 100),
                    max_depth=int(cfg["crawl_max_depth"] or 2),
                    crawl_delay_seconds=float(cfg["crawl_delay_seconds"] or 0),
                    time_budget_seconds=float(
                        cfg["crawl_time_budget_seconds"] or 60
                    ),
                    respect_robots_txt=bool(cfg["crawl_respect_robots_txt"]),
                    include_regex=cfg["include_regex"] or None,
                    exclude_regex=cfg["exclude_regex"] or None,
                    normalize_opts=normalize_opts,
                )
                raw_urls = list(cr.urls)
                warnings.extend(cr.warnings)
                if cr.hit_max_pages:
                    warnings.append(
                        f"Crawl hit max_pages={cfg['crawl_max_pages']}; inventory may be incomplete."
                    )
                if cr.hit_time_budget:
                    warnings.append(
                        f"Crawl hit time budget ({cfg['crawl_time_budget_seconds']}s); inventory may be incomplete."
                    )
                if cr.pages_skipped_robots:
                    warnings.append(
                        f"{cr.pages_skipped_robots} URL(s) skipped by robots.txt"
                    )
            else:
                raise ProcessorException(
                    message=f"Unknown source_type {source_type!r}",
                    url=source_url,
                    status_code=self.fetcher.get_last_status_code(),
                    screenshot=self.fetcher.screenshot,
                    xpath_data=self.fetcher.xpath_data,
                )
        except ProcessorException:
            raise
        except Exception as exc:
            logger.exception(
                f"site_inventory_diff: extraction failed for {source_url!r}"
            )
            raise ProcessorException(
                message=f"Inventory extraction failed: {exc!r}",
                url=source_url,
                status_code=self.fetcher.get_last_status_code(),
                screenshot=self.fetcher.screenshot,
                xpath_data=self.fetcher.xpath_data,
            )

        # Normalize, filter by origin / regex, dedupe, sort.
        inc_re = _regex_or_none(cfg["include_regex"])
        exc_re = _regex_or_none(cfg["exclude_regex"])

        canon: list[str] = []
        for u in raw_urls:
            c = normalize.canonical_url(u, base_url=source_url, **normalize_opts)
            if not c:
                continue
            if cfg["same_origin_only"] and not normalize.same_origin(c, source_url):
                continue
            if inc_re and not inc_re.search(c):
                continue
            if exc_re and exc_re.search(c):
                continue
            canon.append(c)

        urls_sorted = normalize.dedupe_and_sort(canon)

        # Emit snapshot + persist meta.
        snapshot, meta = self._emit_snapshot(
            urls_sorted,
            source_url=source_url,
            mode=actual_mode,
            warnings=warnings,
        )
        self._save_inventory_meta(meta)

        # Change detection via MD5 of the *body* (not the header) — so the
        # timestamp line doesn't cause spurious changes on every check.
        body_only = "\n".join(urls_sorted)
        fetched_md5 = hashlib.md5(body_only.encode("utf-8")).hexdigest()
        update_obj["previous_md5"] = fetched_md5

        changed_detected = False
        prev = watch.get("previous_md5")
        if prev and prev != fetched_md5:
            changed_detected = True
        elif not prev and urls_sorted:
            # First successful run with content — record baseline, no alert.
            changed_detected = False

        logger.debug(
            f"site_inventory_diff: {len(urls_sorted)} URLs (mode={actual_mode}) "
            f"prev_md5={prev!r} new_md5={fetched_md5!r} changed={changed_detected}"
        )

        return changed_detected, update_obj, snapshot
