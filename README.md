# onChange by Sairo

**Self-hosted web-page change monitoring, accessibility-first, with a
modern brand and a design system you can actually follow.**

`onChange by Sairo` watches web pages for you — prices, product stock,
release notes, court listings, CVEs, job boards, Wikipedia articles,
anything. When something changes, it tells you, on your channel of
choice. You run it on your own machine, your own data never leaves.

**Live instance (coming soon):** <https://change.sairo.app>

---

## A friendly fork

`onChange by Sairo` is a respectful fork of the excellent open-source
project **[changedetection.io](https://github.com/dgtlmoon/changedetection.io)**
by Leigh Morresi and contributors, distributed under the
[Apache License 2.0](LICENSE).

Please read [`ATTRIBUTION.md`](ATTRIBUTION.md) and [`NOTICE`](NOTICE) —
they explain our upstream lineage, list every significant change we have
made, and make our trademark & endorsement stance explicit.

> We did not build this from scratch. `changedetection.io` is a genuinely
> good piece of software, and the fact that the upstream team chose a
> permissive licence is the whole reason this fork can exist. **Thank you.**

If you are looking for the official upstream product or its maintained
SaaS offering, please use the upstream project — not this one.

---

## What’s different in this fork

The short version (full list in [`ATTRIBUTION.md`](ATTRIBUTION.md)):

1. **New brand & design system.**
   Renamed to *onChange by Sairo*, new indigo/slate colour palette,
   Inter typography, 4 px spacing rhythm, documented in
   [`DESIGN.md`](DESIGN.md).
2. **Watch Templates** — 15 one-click recipes (Amazon, GitHub releases,
   CVEs, Wikipedia, arXiv, …).
3. **Site URL inventory & crawler** — new `site_inventory_diff`
   processor that tracks when *pages* are added to or removed from a
   site, not just text changes on one URL. Four sources you can point
   it at:
   - `auto` — sniff a URL's response and pick the right mode.
   - `sitemap` — read `sitemap.xml` or a sitemap index (follows child
     sitemaps up to 50 deep).
   - `html` — parse `<a href>` links from a listing page, with CSS
     scoping and include/exclude regex.
   - `crawl` *(beta)* — bounded same-origin BFS crawl with
     robots.txt-respect (default on), per-request delay, max pages /
     depth / time-budget caps, SSRF filtering, skip-if-seed-unchanged,
     and a periodic full-walk so silent deep-page changes still surface.

   The snapshot is just a sorted URL list per line, so it plugs into
   **every existing feature for free** — the diff viewer renders
   added/removed URLs, history navigation works, RSS feeds carry the
   delta, and the existing fetcher stack (Playwright/Selenium) is used
   for the non-crawl modes. New notification tokens `{{new_urls}}`,
   `{{removed_urls}}`, `{{new_urls_count}}`, `{{removed_urls_count}}`,
   `{{url_count}}`, `{{inventory_mode}}`, and `{{inventory_warnings}}`
   work in any Apprise channel. Per-watch CSV export, a tag-level
   rollup dashboard at `/site-inventory/`, and a live crawl-progress
   widget on the Stats tab round it out.
4. **Scheduled digest emails** — summary notifications on a daily /
   weekly cadence via any Apprise destination.
5. **AI-assisted filter builder** — describe what you want to monitor in
   plain English; an Anthropic Claude call returns a CSS/XPath
   suggestion you review before saving.
6. **Security hardening** — non-root Docker user, scoped CORS, pooled
   HTTP sessions, chardet confidence gate, transient-HTTP retry, a
   client-side modal XSS fix, ARIA/mobile accessibility pass.
7. **Mobile-first UX** — a fixed bottom navigation bar (Watches / Groups
   / Search / More) on ≤ 980 px, iOS safe-area-aware hamburger drawer,
   2-column language picker, horizontally scrolling tab strips with
   44 px hit targets, and a rebuilt diff page that stacks From/To
   selectors and gives screenshots the full card width on phones.
   Details in [`ATTRIBUTION.md`](ATTRIBUTION.md#accessibility--frontend-polish).

---

## Quick start

```bash
# Docker
docker run -d --name onchange \
  -p 5000:5000 \
  -v /my/datastore:/datastore \
  ghcr.io/<your-image>/onchange:latest   # or build from source, see below
```

```bash
# From source
git clone https://your-git-host/onchange-sairo.git
cd onchange-sairo
pip install -r requirements.txt
python changedetection.py -d /tmp/onchange-data
# Visit http://localhost:5000
```

### Deploying on Coolify

`onChange by Sairo` ships first-class support for
[Coolify](https://coolify.io) (v4.x, 2025/2026). Everything you need is
already in the repo:

- [`docker-compose.coolify.yml`](docker-compose.coolify.yml) — Coolify-tuned
  compose using `SERVICE_FQDN_*` magic variables, named volumes, and an
  inline healthcheck.
- [`COOLIFY.md`](COOLIFY.md) — step-by-step deployment guide (domains, TLS,
  persistent storage, auto-deploy, the Playwright sidecar, troubleshooting).
- [`.env.example`](.env.example) — **every** environment variable the app
  reads, with defaults, notes, and where to get secrets like
  `ANTHROPIC_API_KEY`.

Point Coolify at `docker-compose.coolify.yml` on the *Docker Compose* build
pack, copy the values you need from `.env.example` into the
*Environment Variables* tab, and deploy. Full walkthrough in
[`COOLIFY.md`](COOLIFY.md).

### Configuration

Every environment variable the app reads is documented in
[`.env.example`](.env.example). Runtime settings (notifications, proxy
lists, browser fetchers, digest emails, AI filter builder) are also
configurable from the in-app **Settings** panel.

---

## Accessibility

We target **WCAG 2.2 Level AA** (which subsumes 2.1 AA and 2.0 AA).
Every visual decision, colour contrast pair, focus behaviour, and
keyboard journey is specified in [`DESIGN.md`](DESIGN.md). If you find
an accessibility regression, please open an issue — we treat those as
blockers, not bugs.

The full WCAG 2.2 AA conformance checklist — including the six new 2.2
success criteria (2.4.11 Focus Not Obscured, 2.5.7 Dragging Movements,
2.5.8 Target Size Minimum, 3.2.6 Consistent Help, 3.3.7 Redundant Entry,
3.3.8 Accessible Authentication) — is documented in
[`DESIGN.md` § 6](DESIGN.md#6-accessibility-wcag-22-aa).

Highlights of how we conform:

- **1.4.3 / 1.4.11 Contrast** — every text/background pair is logged in
  `DESIGN.md` § 2.4 and exceeds 4.5 : 1 for normal text, 3 : 1 for
  large text and non-text UI.
- **1.4.10 Reflow** — layouts reflow at 320 CSS px without horizontal
  scrolling; mobile bottom-nav and stacked diff page enforce this.
- **1.4.12 Text Spacing** — body text uses `rem` units and respects
  user-set spacing overrides.
- **2.1.1 / 2.1.2 Keyboard** — every interactive control is reachable
  and operable via keyboard with no traps.
- **2.4.7 Focus Visible** — 2 px indigo focus ring with 2 px offset on
  every focusable element; never removed.
- **2.4.11 Focus Not Obscured (new in 2.2)** — sticky headers, the
  mobile bottom-nav, and toast region are sized so the focused element
  is never fully hidden; `scroll-margin` is applied to anchored targets.
- **2.5.5 / 2.5.8 Target Size** — 44 × 44 CSS px on touch viewports
  (≤ 760 px) and ≥ 24 × 24 CSS px everywhere else, with adequate
  spacing between adjacent targets.
- **2.5.7 Dragging Movements (new in 2.2)** — every drag-only
  interaction (re-ordering watches, resizing panes) has a keyboard or
  click-based alternative.
- **3.2.6 Consistent Help (new in 2.2)** — the support / docs link
  appears in the same position on every page (header on desktop,
  "More" tab on mobile).
- **3.3.7 Redundant Entry (new in 2.2)** — multi-step flows
  (watch creation, restore, import) pre-fill or auto-populate any
  value the user has already entered.
- **3.3.8 Accessible Authentication (new in 2.2)** — login does not
  require a cognitive-function test; password managers and browser
  autofill are not blocked, and the password field allows paste.
- **4.1.2 / 4.1.3 Name, Role, Value & Status Messages** — custom
  widgets follow the WAI-ARIA Authoring Practices; toasts use
  `role="status"` (neutral) or `role="alert"` (errors).

We test pages against axe-core / Lighthouse and screen readers (VoiceOver
on macOS/iOS, NVDA on Windows) before shipping accessibility-impacting
changes.

The deployed app surfaces two public, indexable accessibility documents
(linked from the footer of every page):

- **`/accessibility`** — the public accessibility statement (conformance
  status, compatibility matrix, known limitations, feedback channels).
- **`/accessibility/vpat`** — the **VPAT 2.5Rev — WCAG 2.2** conformance
  report with per-criterion Supports / Partially Supports / Not
  Applicable findings for every Level A and Level AA success criterion.

---

## Licences

- **Source code:** [Apache License, Version 2.0](LICENSE) — inherited
  from upstream, preserved unchanged.
- **Upstream copyright & notices:** [`NOTICE`](NOTICE).
- **Fork provenance & changelog:** [`ATTRIBUTION.md`](ATTRIBUTION.md).
- **Commercial licence (upstream-only):**
  [`COMMERCIAL_LICENCE.md`](COMMERCIAL_LICENCE.md) applies to the upstream
  `changedetection.io` project and is reproduced only for transparency;
  see the notice at the top of that file.
- **Trademarks:** “changedetection.io” is a trademark of its respective
  owners. “Sairo” and “onChange by Sairo” are marks of Sairo.

---

## Contributing

Bug reports, issues, and pull requests are welcome on **this** repo.
Please do not file issues about this fork on the upstream project. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

All contributions are accepted under the existing Apache 2.0 licence;
no CLA is required.

---

## Support & contact

- **This fork:** open an issue on this repository.
- **Upstream project:**
  [changedetection.io on GitHub](https://github.com/dgtlmoon/changedetection.io).
- **Security disclosure:** see `SECURITY.md` (coming soon); in the
  meantime, please email security@sairo.app with responsible-disclosure
  details.
