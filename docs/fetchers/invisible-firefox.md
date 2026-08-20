# Firefox-based stealth fetcher (proposal)

> Draft proposal, opened to gauge interest before building. Tracking discussion: TBD

## What it would be

A separate pypi package (`changedetection.io-invisible-firefox`) installed via `EXTRA_PACKAGES`, exposing a new option in the Fetch Method dropdown. Mirrors the shape of the existing `changedetection.io-cloak-browser` integration.

## Backend

- patched Firefox 150, stealth applied at the C++ source level (no JS shims to detect)
- source: https://github.com/feder-cr/invisible_firefox (MPL-2, same license as Firefox upstream)
- Python wrapper: https://github.com/feder-cr/invisible_playwright

## Relevance

- #4141 (cloak fetcher broken on install)
- #3645 (native Playwright Firefox)
- #2198 (bot detection evasion)
- #3249 (Camoufox integration, open ~2 years)

## Maintenance

Plugin lives in its own repo. Issues against the plugin route there directly, not to this repo.
