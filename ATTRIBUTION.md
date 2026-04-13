# Attribution & Upstream Provenance

**onChange by Sairo** is a friendly fork of the open-source
[changedetection.io](https://github.com/dgtlmoon/changedetection.io)
project, distributed under the Apache License, Version 2.0.

This document exists to make our lineage explicit and to comply with the
attribution obligations set out in **Section 4** of the Apache License
(preserving copyright, NOTICE, changelog, and disclaiming endorsement).

---

## Upstream project

| Field             | Value                                                          |
|-------------------|----------------------------------------------------------------|
| Project name      | `changedetection.io`                                           |
| Maintainer        | Leigh Morresi (`dgtlmoon`) and the changedetection.io contributors |
| Repository        | https://github.com/dgtlmoon/changedetection.io                |
| Licence           | Apache License 2.0                                             |
| Copyright notice  | Copyright 2020–2025 Leigh Morresi and contributors             |
| Trademark         | `changedetection.io` is a trademark of its respective owners   |

The full, unmodified text of the Apache License 2.0 is included in this
repository at [`LICENSE`](LICENSE). The upstream copyright notices are
preserved in [`NOTICE`](NOTICE).

> We are grateful to Leigh Morresi and to every contributor to
> changedetection.io. This fork exists because the upstream project is
> excellent and permissive enough to build on top of — *thank you*.

---

## What this fork changed

Apache 2.0 § 4(b) requires derivative works to carry "prominent notices
stating that You changed the files." A complete, authoritative list of
changes is available in the commit history of this repository. The
summary below groups the non-trivial modifications.

### Branding & design
- Renamed the user-facing product to **onChange by Sairo**.
- Introduced a new brand design system (colour palette, typography,
  spacing, component tokens). See [`DESIGN.md`](DESIGN.md).
- Refactored the SCSS token layer so every colour flows from a single
  brand palette (`changedetectionio/static/styles/scss/parts/_brand.scss`).
- Replaced the hero copy, page titles, favicons references, and footer
  attribution.

The upstream project’s name, logos, and website URLs are **not** used
for branding of this fork. Wherever they appear in this repository they
are used strictly for attribution and to link back to the original
project.

### New features
- **Watch Templates** — one-click recipes for common monitoring targets
  (Amazon, GitHub releases, CVE feeds, Wikipedia, etc.).
  `changedetectionio/blueprint/watch_templates/`
- **Scheduled Digest emails** — periodic summary notifications via the
  existing Apprise pipeline. `changedetectionio/digest.py`
- **AI-assisted Filter Builder** — natural-language → CSS/XPath
  suggestion via Anthropic Claude. `changedetectionio/blueprint/ai_filter/`

### Security & hardening
- Non-root Docker runtime user.
- Scoped CORS to `/api/*` only; configurable allow-list.
- Thread-local pooled `requests.Session` for the fetcher.
- Chardet confidence gate to eliminate encoding-flip false positives.
- urllib3 retry now covers transient HTTP 429/502/503/504.
- Fixed an XSS vector in the client-side modal dialog.
- Fixed a race in `was_edited` consumption that could silently drop user
  edits between a processor and the worker reset.
- Added a `trigger_text_missing_warning` field to surface silent
  false-negative filters.

### Accessibility & frontend polish
- `<header>` / `<nav>` / `<main>` semantic landmarks.
- Skip-to-content link.
- `aria-modal`, `role="alert"`, `role="status"` on dialogs and live
  regions.
- 44 px minimum tap-target enforcement below 760 px.
- Deferred loading of jQuery and its dependents.
- Production-gated `console.log` (enable with `?debug=1`).

#### Mobile UX

- **Fixed bottom navigation bar** (≤ 980 px, authenticated sessions
  only): Watches / Groups / Search / More. `Search` delegates to the
  existing modal, `More` triggers the hamburger drawer — no duplicate
  modal or drawer logic. `body.has-bottom-nav` lifts the realtime-offline
  badge and `#bottom-horizontal-offscreen` so they don't stack on top
  of the bar. `env(safe-area-inset-bottom)` honored for notched devices.
- **Watch list** — URL/title columns wrap instead of overflowing,
  pause/mute each get their own 44×44 px tap target, stats row and
  bulk-ops toolbar wrap gracefully on narrow screens.
- **Hamburger drawer** — width clamped to `min(85vw, 320px)`,
  `safe-area-inset-top/bottom` applied, ease-out animation replaces the
  previous overshoot bezier, `overscroll-behavior: contain` so drawer
  scrolling doesn't chain to the page.
- **Tabs** (edit / diff / settings) — become a horizontal scroll strip
  below 760 px with 44 px hit targets; `scroll-margin-top` reduced from
  200 px to 90 px on mobile so tab anchors don't scroll past the
  viewport.
- **Diff page** — From/To version selectors stack full-width, checkboxes
  wrap in a compact flex row, Prev/Next share the row equally,
  screenshots use the full card width, and the desktop-only 40 px
  `#diff-col` left-padding is dropped.
- **Language modal** — 2-column grid on ≤ 600 px with ellipsis guards
  for long language names.

---

## Third-party components

`onChange by Sairo` inherits all the third-party dependencies of
`changedetection.io`. The runtime dependencies are pinned in
[`requirements.txt`](requirements.txt). Notable third-party components
include (non-exhaustive):

| Component       | Licence                        | Project URL |
|-----------------|--------------------------------|-------------|
| Flask           | BSD-3-Clause                   | https://flask.palletsprojects.com/ |
| WTForms         | BSD-3-Clause                   | https://wtforms.readthedocs.io/ |
| Apprise         | BSD-2-Clause                   | https://github.com/caronc/apprise |
| Playwright      | Apache 2.0                     | https://playwright.dev/ |
| Selenium        | Apache 2.0                     | https://www.selenium.dev/ |
| Pure CSS        | Yahoo BSD-3                    | https://purecss.io/ |
| jQuery          | MIT                            | https://jquery.com/ |
| Feather icons   | MIT                            | https://feathericons.com/ |
| loguru          | MIT                            | https://github.com/Delgan/loguru |
| chardet         | LGPL-2.1                       | https://pypi.org/project/chardet/ |
| brotli          | MIT                            | https://github.com/google/brotli |

Each dependency retains its own licence and copyright; nothing in this
document supersedes those licences.

---

## Trademark & endorsement

- The name **"changedetection.io"** and any associated logos are
  trademarks of their respective owners. They are referenced in this
  repository only to identify the upstream project and to comply with
  the attribution obligations of the Apache License. Their use here is
  neither a claim of ownership nor a claim of endorsement.
- The names **"onChange by Sairo"**, **"Sairo"**, and the Sairo marks
  are marks of Sairo.

The upstream `changedetection.io` project and its maintainers are not
affiliated with, sponsor, or endorse this fork. Please do not raise
support or feature requests related to **onChange by Sairo** on the
upstream repository.

---

## Licence for your changes

By contributing to this fork, you agree that your contributions are
licensed under the same Apache License, Version 2.0 that covers the
rest of the project. No CLA is required.

If you spot an attribution we have missed, or a licence we should
surface more prominently, please open an issue — we take compliance
seriously.
