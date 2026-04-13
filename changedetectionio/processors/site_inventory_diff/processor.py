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
# advertise browser_steps / visual_selector. For inventory watches the
# existing Filters & Triggers pipeline doesn't meaningfully apply either:
# the snapshot is a sorted list of URLs, not page text, so ignore_text /
# trigger_text would silently do nothing. The processor exposes its own
# include_regex / exclude_regex / css_scope knobs for URL-level filtering
# (see forms.py), and setting supports_text_filters_and_triggers=False
# keeps the misleading tab hidden.
supports_visual_selector = False
supports_browser_steps = False
supports_text_filters_and_triggers = False
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
        # Skip-if-seed-unchanged heuristic for crawl mode. On every scheduled
        # run we hash the seed HTML and, if it hasn't changed since the last
        # FULL crawl AND the watch wasn't edited AND we're inside the
        # safety-valve window below, we short-circuit with
        # checksumFromPreviousCheckWasTheSame(). This avoids hammering a
        # site whose homepage is truly static while still guaranteeing a
        # periodic full recrawl to catch silent deep-page changes.
        "crawl_skip_if_seed_unchanged": True,
        "crawl_full_crawl_every_hours": 24,
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

    def _resolve_watch_http_context(
        self,
    ) -> tuple[Optional[str], dict, Optional[str]]:
        """Extract proxy URL + merged request headers + User-Agent for the
        current watch, using the same precedence rules as
        :meth:`~difference_detection_processor.call_browser` so crawl-mode
        fetches look like the watch's configured fetcher to the remote site.

        Returns ``(proxy_url, headers, user_agent)`` where any element may be
        ``None`` / empty when the watch has no override.
        """
        from changedetectionio.jinja2_custom import render as jinja_render

        # --- Proxy -----------------------------------------------------
        proxy_url: Optional[str] = None
        try:
            preferred_proxy_id = self.datastore.get_preferred_proxy_for_watch(
                uuid=self.watch.get("uuid")
            )
            if preferred_proxy_id:
                proxy_entry = self.datastore.proxy_list.get(preferred_proxy_id) or {}
                proxy_url = proxy_entry.get("url") or None
        except Exception as exc:
            logger.debug(
                f"site_inventory_diff: proxy resolution failed: {exc!r}"
            )

        # --- Headers ---------------------------------------------------
        # Resolve what fetch_backend the watch would have used so the default
        # User-Agent matches the main fetcher's UA.
        fetch_backend = self.watch.get("fetch_backend", "system")
        if not fetch_backend or fetch_backend == "system":
            fetch_backend = self.datastore.data["settings"]["application"].get(
                "fetch_backend"
            )

        user_agent: Optional[str] = None
        ua_map = self.datastore.data["settings"]["requests"].get("default_ua") or {}
        if isinstance(ua_map, dict) and ua_map.get(fetch_backend):
            user_agent = ua_map.get(fetch_backend)

        merged: dict[str, str] = {}
        try:
            merged.update(self.datastore.get_all_base_headers() or {})
            merged.update(
                self.datastore.get_all_headers_in_textfile_for_watch(
                    uuid=self.watch.get("uuid")
                )
                or {}
            )
        except Exception as exc:
            logger.debug(
                f"site_inventory_diff: base/textfile header merge failed: {exc!r}"
            )
        merged.update(self.watch.get("headers", {}) or {})

        # Don't ask for brotli — our minimal `requests`-based client
        # doesn't decode it. Parity with base.py::call_browser.
        if "Accept-Encoding" in merged and "br" in merged["Accept-Encoding"]:
            merged["Accept-Encoding"] = merged["Accept-Encoding"].replace(", br", "")

        # Jinja-render header values exactly like the main fetcher does.
        for k in list(merged.keys()):
            try:
                merged[k] = jinja_render(template_str=merged[k])
            except Exception as exc:
                logger.debug(
                    f"site_inventory_diff: header jinja render failed for {k!r}: {exc!r}"
                )

        # If the caller wants a specific UA, hoist it out of the dict so the
        # crawler can apply it to both robots.txt matching and the HTTP
        # Authorization header construction.
        if "User-Agent" in merged and not user_agent:
            user_agent = merged.pop("User-Agent")
        else:
            merged.pop("User-Agent", None)

        return proxy_url, merged, user_agent

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
        _crawl_bookkeeping: Optional[dict] = None

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
                # Crawl mode runs its own HTTP client because robots.txt, per-
                # request delay, and SSRF per-URL checks don't fit the main
                # fetcher's one-shot contract. To preserve the user's intent
                # we still propagate their configured proxy, custom request
                # headers, timeout, and UA into the crawler — and we seed it
                # with the body the worker already fetched so we don't make a
                # redundant HTTP call for the seed URL itself.
                from . import crawler

                proxy_url, request_headers, user_agent_str = (
                    self._resolve_watch_http_context()
                )
                timeout = (
                    float(
                        self.datastore.data["settings"]["requests"].get(
                            "timeout"
                        )
                        or 10.0
                    )
                )
                seed_body_for_crawler: Optional[str] = None
                if self.fetcher.content and isinstance(self.fetcher.content, str):
                    seed_body_for_crawler = self.fetcher.content

                # Skip-if-seed-unchanged (#8). Cheap heuristic: if the seed
                # HTML is byte-identical to what it was at the last full
                # crawl, AND the watch wasn't edited, AND we're still inside
                # the "max skip age" window, don't re-walk the site. The
                # window makes sure silent deep-page changes still get
                # caught periodically.
                seed_md5 = hashlib.md5(
                    (seed_body_for_crawler or "").encode("utf-8")
                ).hexdigest()
                last_meta = self.get_extra_watch_config(CONFIG_FILENAME).get(
                    "site_inventory_diff_last", {}
                ) or {}
                last_seed_md5 = last_meta.get("seed_md5")
                last_full_crawl_at = int(last_meta.get("last_full_crawl_unix", 0) or 0)
                max_skip_age_s = int(
                    (cfg.get("crawl_full_crawl_every_hours") or 24) * 3600
                )
                seed_unchanged = (
                    seed_body_for_crawler
                    and last_seed_md5
                    and last_seed_md5 == seed_md5
                )
                inside_skip_window = (
                    last_full_crawl_at > 0
                    and (int(time.time()) - last_full_crawl_at) < max_skip_age_s
                )
                if (
                    cfg.get("crawl_skip_if_seed_unchanged")
                    and not force_reprocess
                    and not watch.was_edited
                    and seed_unchanged
                    and inside_skip_window
                ):
                    logger.debug(
                        f"site_inventory_diff: skip crawl (seed md5 unchanged, "
                        f"last full crawl {int(time.time()) - last_full_crawl_at}s ago)"
                    )
                    raise checksumFromPreviousCheckWasTheSame()

                # Progress callback for #9 — write a small crawl_progress
                # subtree into the meta file every few successful fetches.
                # The Stats-tab widget reads this to show live progress.
                def _on_progress(cr_live):
                    try:
                        self.update_extra_watch_config(
                            CONFIG_FILENAME,
                            {
                                "site_inventory_diff_progress": {
                                    "pages_fetched": cr_live.pages_fetched,
                                    "pages_failed": cr_live.pages_failed,
                                    "pages_skipped_robots": cr_live.pages_skipped_robots,
                                    "pages_skipped_ssrf": cr_live.pages_skipped_ssrf,
                                    "updated_at_unix": int(time.time()),
                                    "max_pages": int(cfg["crawl_max_pages"] or 100),
                                }
                            },
                            merge=True,
                        )
                    except Exception as exc:
                        logger.debug(f"progress persist failed: {exc!r}")

                cr = crawler.crawl(
                    seed_url=source_url,
                    max_pages=int(cfg["crawl_max_pages"] or 100),
                    max_depth=int(cfg["crawl_max_depth"] or 2),
                    crawl_delay_seconds=float(cfg["crawl_delay_seconds"] or 0),
                    time_budget_seconds=float(
                        cfg["crawl_time_budget_seconds"] or 60
                    ),
                    respect_robots_txt=bool(cfg["crawl_respect_robots_txt"]),
                    user_agent=user_agent_str or crawler.DEFAULT_USER_AGENT,
                    request_timeout=timeout,
                    include_regex=cfg["include_regex"] or None,
                    exclude_regex=cfg["exclude_regex"] or None,
                    normalize_opts=normalize_opts,
                    proxy_url=proxy_url,
                    extra_headers=request_headers,
                    seed_body=seed_body_for_crawler,
                    seed_content_type=update_obj["content-type"] or "text/html",
                    on_progress=_on_progress,
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

                # Record the seed MD5 and full-crawl timestamp so the next
                # scheduled check can consider skipping. We persist these
                # alongside the main meta below, not here.
                actual_mode = "crawl"
                _crawl_bookkeeping = {
                    "seed_md5": seed_md5,
                    "last_full_crawl_unix": int(time.time()),
                }
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
        if _crawl_bookkeeping:
            meta.update(_crawl_bookkeeping)
        self._save_inventory_meta(meta)
        # Clear any transient crawl-progress record — the run is complete,
        # so a partial progress ping would just confuse the Stats widget.
        try:
            self.update_extra_watch_config(
                CONFIG_FILENAME,
                {"site_inventory_diff_progress": None},
                merge=True,
            )
        except Exception:
            pass

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
