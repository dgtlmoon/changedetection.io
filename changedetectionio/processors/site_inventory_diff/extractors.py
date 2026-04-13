"""
URL extractors for the site_inventory_diff processor.

Three sources are supported:

* :func:`extract_from_sitemap_xml` — single sitemap.xml; also transparently
  unwraps gzipped sitemaps when passed bytes.
* :func:`extract_from_sitemap_index` — parses a <sitemapindex>, follows each
  child sitemap, and returns the flattened URL set. Capped to avoid abuse.
* :func:`extract_from_html` — grabs ``<a href>`` anchors; optionally scoped to a
  CSS selector.

Each extractor returns an iterable of *raw* URL strings. Callers are expected
to run every URL through :func:`normalize.canonical_url` before storage.
"""

from __future__ import annotations

import gzip
import io
import re
from typing import Callable, Iterable, Optional
from urllib.parse import urljoin

from loguru import logger


# Hard cap for sitemap-index recursion. Raising this is fine but it's a good
# fuse against pathological sites and against misconfigured test fixtures.
SITEMAP_INDEX_CHILD_CAP = 50


# ----- Type sniffing ------------------------------------------------------

_SITEMAPINDEX_HINT = re.compile(rb"<\s*sitemapindex\b", re.IGNORECASE)
_URLSET_HINT = re.compile(rb"<\s*urlset\b", re.IGNORECASE)


def sniff_source_type(
    content: bytes | str,
    content_type: str = "",
    url: str = "",
) -> str:
    """Return one of: ``sitemap_index``, ``sitemap``, ``html``.

    Uses content-type first, then URL suffix, then a fast byte-level sniff.
    Never raises — falls back to ``html`` on any uncertainty.
    """
    if isinstance(content, str):
        probe = content[:4096].encode("utf-8", errors="replace")
    else:
        probe = content[:4096] if content else b""

    ct = (content_type or "").lower()
    if any(tok in ct for tok in ("xml", "sitemap")):
        if _SITEMAPINDEX_HINT.search(probe):
            return "sitemap_index"
        return "sitemap"

    url_low = (url or "").lower()
    if url_low.endswith((".xml", ".xml.gz")) or "sitemap" in url_low.rsplit("/", 1)[-1]:
        if _SITEMAPINDEX_HINT.search(probe):
            return "sitemap_index"
        if _URLSET_HINT.search(probe):
            return "sitemap"

    if _SITEMAPINDEX_HINT.search(probe):
        return "sitemap_index"
    if _URLSET_HINT.search(probe):
        return "sitemap"

    return "html"


def _maybe_gunzip(content: bytes) -> bytes:
    """Transparently decompress a gzipped sitemap; return original on failure."""
    if not content or len(content) < 2 or content[:2] != b"\x1f\x8b":
        return content
    try:
        return gzip.decompress(content)
    except (OSError, EOFError, ValueError) as exc:
        logger.debug(f"gunzip failed on sitemap payload: {exc!r}")
        return content


# ----- Sitemap parsing ----------------------------------------------------

# We import lxml lazily because the rest of the module (sniffing, types) is
# useful without it — and lxml is already a hard dep via html_tools.
def _lxml_fromstring(payload: bytes):
    from lxml import etree

    # Defeat billion-laughs / external-entity attacks.
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        huge_tree=False,
        recover=True,
    )
    return etree.fromstring(payload, parser=parser)


def _iter_loc_elements(root):
    """Yield the text contents of every ``<loc>`` element at the given root.

    Namespace-agnostic: sitemap.org uses ``xmlns="http://www.sitemaps.org/…"``
    but some CMSes emit bare elements. We match by local-name.
    """
    if root is None:
        return
    for el in root.iter():
        # Strip namespace prefix for matching.
        tag = el.tag
        if isinstance(tag, str) and "}" in tag:
            tag = tag.split("}", 1)[1]
        if tag == "loc" and el.text:
            yield el.text.strip()


def extract_from_sitemap_xml(content: bytes | str) -> list[str]:
    """Return every ``<loc>`` value in a ``<urlset>`` sitemap."""
    if isinstance(content, str):
        payload = content.encode("utf-8", errors="replace")
    else:
        payload = content
    payload = _maybe_gunzip(payload)

    try:
        root = _lxml_fromstring(payload)
    except Exception as exc:  # lxml can raise various XMLSyntaxError subtypes
        logger.info(f"Sitemap XML parse failed: {exc!r}; returning empty list")
        return []

    return list(_iter_loc_elements(root))


def extract_from_sitemap_index(
    content: bytes | str,
    fetch_child: Callable[[str], Optional[bytes]],
    *,
    child_cap: int = SITEMAP_INDEX_CHILD_CAP,
) -> tuple[list[str], bool]:
    """Flatten a ``<sitemapindex>`` by fetching each child sitemap.

    Args:
        content: Raw XML of the sitemap index.
        fetch_child: Callable that returns raw bytes for a child sitemap URL,
            or ``None`` if the fetch failed. The caller owns HTTP, proxying,
            timeouts, etc.
        child_cap: Maximum number of child sitemaps to follow.

    Returns:
        ``(urls, capped)`` where ``capped`` is True if ``child_cap`` was hit
        (signal to surface a warning in the UI).
    """
    if isinstance(content, str):
        payload = content.encode("utf-8", errors="replace")
    else:
        payload = content
    payload = _maybe_gunzip(payload)

    try:
        root = _lxml_fromstring(payload)
    except Exception as exc:
        logger.info(f"Sitemap-index XML parse failed: {exc!r}")
        return [], False

    child_urls = list(_iter_loc_elements(root))
    capped = False
    if len(child_urls) > child_cap:
        logger.warning(
            f"Sitemap index has {len(child_urls)} children; capping at {child_cap}"
        )
        child_urls = child_urls[:child_cap]
        capped = True

    all_urls: list[str] = []
    for child_url in child_urls:
        try:
            body = fetch_child(child_url)
        except Exception as exc:
            logger.info(f"Child sitemap fetch raised for {child_url}: {exc!r}")
            continue
        if not body:
            continue
        all_urls.extend(extract_from_sitemap_xml(body))

    return all_urls, capped


# ----- HTML anchor extraction --------------------------------------------

def extract_from_html(
    html: str,
    base_url: str,
    css_scope: Optional[str] = None,
) -> list[str]:
    """Extract ``href`` values from anchor tags in ``html``.

    Args:
        html: Decoded HTML source.
        base_url: Absolute URL of the page (used to resolve relative hrefs).
        css_scope: Optional CSS selector; only anchors inside a matching
            element are returned. When falsy, all anchors are returned.
    """
    if not html:
        return []

    # Use lxml for robust parsing + CSS selection. It's already a hard dep.
    from lxml import html as lxml_html

    try:
        doc = lxml_html.fromstring(html)
    except Exception as exc:
        logger.info(f"HTML parse failed in extract_from_html: {exc!r}")
        return []

    # Resolve relative URLs using the parsed document's <base href>
    # or the supplied base_url.
    try:
        doc.make_links_absolute(base_url, resolve_base_href=True)
    except Exception:
        pass

    roots = [doc]
    if css_scope:
        try:
            # .cssselect() requires the cssselect package, which lxml already
            # depends on transitively. Fall back to xpath on failure.
            matches = doc.cssselect(css_scope)
            if matches:
                roots = matches
            else:
                return []  # scope given but nothing matched — empty is correct
        except Exception as exc:
            logger.info(f"cssselect failed for scope {css_scope!r}: {exc!r}")
            roots = [doc]

    out: list[str] = []
    for root in roots:
        for a in root.iter("a"):
            href = a.get("href")
            if not href:
                continue
            # Some pages use Jinja-like {{...}} in href placeholders; skip those.
            if "{{" in href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
                continue
            # make_links_absolute may not have resolved every edge case.
            try:
                abs_url = urljoin(base_url, href.strip())
            except ValueError:
                continue
            out.append(abs_url)
    return out
