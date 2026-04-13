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
3. **Scheduled digest emails** — summary notifications on a daily /
   weekly cadence via any Apprise destination.
4. **AI-assisted filter builder** — describe what you want to monitor in
   plain English; an Anthropic Claude call returns a CSS/XPath
   suggestion you review before saving.
5. **Security hardening** — non-root Docker user, scoped CORS, pooled
   HTTP sessions, chardet confidence gate, transient-HTTP retry, a
   client-side modal XSS fix, ARIA/mobile accessibility pass.

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

Full configuration (env vars, proxies, browser fetchers, digest emails,
AI filter builder) is documented in the in-app **Settings** panel.

---

## Accessibility

We target **WCAG 2.1 Level AA**. Every visual decision, colour
contrast pair, focus behaviour, and keyboard journey is specified in
[`DESIGN.md`](DESIGN.md). If you find an accessibility regression,
please open an issue — we treat those as blockers, not bugs.

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
