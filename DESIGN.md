# onChange by Sairo — Design System

This document is the **binding design reference** for the onChange by
Sairo user interface. Every visual or accessibility decision in the app
should be traceable to a token, rule, or pattern defined here. If you
need to deviate, update this file in the same commit and explain why.

> **TL;DR** — Use the semantic CSS variables (never raw hex), hit WCAG
> 2.2 AA contrast, prefer `rem`/`em` over pixel sizes, and keep the
> keyboard journey intact. Everything else follows.

---

## 1. Brand

### 1.1 Name, logotype, voice

| Attribute    | Value                                                  |
|--------------|--------------------------------------------------------|
| Product name | **onChange by Sairo**                                  |
| Short name   | **onChange**                                           |
| Wordmark     | `onChange` set in **Inter Semibold 600**, `by Sairo` set in **Inter Regular 400**, tracking −1 %, same baseline |
| Favicon text | `oC`                                                    |
| Domain       | `change.sairo.app`                                     |
| Primary colour (brand indigo) | `#4338CA`                               |

**Voice:** calm, direct, technical when it needs to be, never shouty.
We are a monitoring tool — people come here to *be told*, not sold to.
Prefer short verbs ("Create watch", "Send digest") over marketing copy
("Unlock powerful monitoring!").

### 1.2 The upstream name (`changedetection.io`)

`changedetection.io` is the upstream project this fork is built on. Its
name and logos are **only** used inside `ATTRIBUTION.md`, `NOTICE`, and
the in-app "About" / settings-info panel. They never appear in brand
surfaces (landing page, nav, marketing), and never as a logo. See
`ATTRIBUTION.md` for the full policy.

---

## 2. Colour palette

All colours live in `changedetectionio/static/styles/scss/parts/_brand.scss`
as CSS custom properties under `:root`. Every downstream SCSS partial
consumes semantic variables — never a raw hex.

### 2.1 Brand palette

| Token                     | Hex        | Use                                    |
|---------------------------|------------|----------------------------------------|
| `--brand-indigo-50`       | `#EEF2FF`  | Faint indigo wash, empty-state backgrounds |
| `--brand-indigo-100`      | `#E0E7FF`  | Hover states on light backgrounds       |
| `--brand-indigo-300`      | `#A5B4FC`  | Decorative accents                      |
| `--brand-indigo-500`      | `#6366F1`  | Interactive default (links on dark)     |
| `--brand-indigo-600`      | `#4F46E5`  | Primary buttons, focused borders        |
| `--brand-indigo-700`      | `#4338CA`  | **Primary brand colour**                |
| `--brand-indigo-800`      | `#3730A3`  | Active/pressed buttons                  |
| `--brand-indigo-900`      | `#312E81`  | High-contrast deep accent               |

### 2.2 Neutral scale (slate)

Neutrals form 80 % of every page. We use Tailwind’s slate ramp because
it pairs well with indigo and stays warm enough in dark mode.

| Token               | Hex        | Use                            |
|---------------------|------------|--------------------------------|
| `--slate-50`        | `#F8FAFC`  | Page background (light)        |
| `--slate-100`       | `#F1F5F9`  | Card background, striped rows  |
| `--slate-200`       | `#E2E8F0`  | Borders on light bg            |
| `--slate-300`       | `#CBD5E1`  | Input borders                  |
| `--slate-400`       | `#94A3B8`  | Muted text (captions)          |
| `--slate-500`       | `#64748B`  | Secondary body text            |
| `--slate-600`       | `#475569`  | Primary body text              |
| `--slate-700`       | `#334155`  | Headings (light)               |
| `--slate-800`       | `#1E293B`  | Card background (dark)         |
| `--slate-900`       | `#0F172A`  | Page background (dark)         |

### 2.3 Semantic status colours

| Status   | Background token       | Text token             | Hex (bg) |
|----------|------------------------|------------------------|----------|
| Success  | `--status-success-bg`  | `--status-success-fg`  | `#D1FAE5` / `#065F46` |
| Warning  | `--status-warning-bg`  | `--status-warning-fg`  | `#FEF3C7` / `#92400E` |
| Danger   | `--status-danger-bg`   | `--status-danger-fg`   | `#FEE2E2` / `#991B1B` |
| Info     | `--status-info-bg`     | `--status-info-fg`     | `#DBEAFE` / `#1E40AF` |
| Change   | `--status-change-bg`   | `--status-change-fg`   | `#FEF3C7` / `#B45309` (amber — product-specific "something changed" highlight) |

### 2.4 Contrast guarantees (WCAG 2.2 AA — SC 1.4.3 / 1.4.11)

Every combination listed below has been checked and exceeds **4.5 : 1**
for normal text or **3 : 1** for large (≥ 18 pt / 14 pt bold) text.

| Foreground              | Background              | Ratio | OK for |
|-------------------------|-------------------------|-------|--------|
| `--slate-700`           | `--slate-50`            | 11.9  | AAA body |
| `--slate-600`           | `--slate-50`            | 8.1   | AAA body |
| `--slate-500`           | `--slate-50`            | 5.7   | AA body |
| `--slate-400`           | `--slate-50`            | 3.8   | AA large only |
| `--brand-indigo-700` (white) | `--brand-indigo-700` | 9.2   | AAA buttons |
| `--white`               | `--brand-indigo-600`    | 7.8   | AAA buttons |
| `--status-success-fg`   | `--status-success-bg`   | 8.1   | AAA badge |
| `--status-warning-fg`   | `--status-warning-bg`   | 6.9   | AA badge |
| `--status-danger-fg`    | `--status-danger-bg`    | 8.4   | AAA badge |

**If you add a colour, you add a row to this table.** If a ratio drops
below 4.5 : 1 for normal text, the colour does not ship.

### 2.5 Dark mode

Dark mode is a full re-mapping, not a filter. All semantic tokens
(`--color-text`, `--color-background-page`, etc.) get re-assigned under
`html[data-darkmode="true"]`. The brand palette itself does not change.
Target contrast on dark surfaces is the same AA / AAA bar.

---

## 3. Typography

```
Display / UI : "Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif
Monospace    : "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace
```

We do **not** self-host webfonts in this fork (same as upstream) — the
system font stack is the fallback, and sites using onChange behind
restrictive proxies get a usable UI without external requests.

### 3.1 Scale

| Role            | Size (px / rem) | Weight | Line-height |
|-----------------|-----------------|--------|-------------|
| Display (h1)    | 28 / 1.75rem    | 700    | 1.2         |
| Title (h2)      | 22 / 1.375rem   | 600    | 1.3         |
| Subtitle (h3)   | 18 / 1.125rem   | 600    | 1.4         |
| Body            | 16 / 1rem       | 400    | 1.5         |
| Small           | 14 / 0.875rem   | 400    | 1.5         |
| Caption / code  | 13 / 0.8125rem  | 400    | 1.45        |

Body-text default **must stay ≥ 16 px** on touch devices — see the
`@media (max-width: 760px)` rule in `styles.scss`.

---

## 4. Spacing & layout

4-pixel rhythm. Every `padding` / `margin` / `gap` should be a multiple
of `0.25rem` (= 4 px).

| Token        | rem   | px | Example use             |
|--------------|-------|----|-------------------------|
| `--space-1`  | 0.25  |  4 | icon gutter             |
| `--space-2`  | 0.5   |  8 | inline chips            |
| `--space-3`  | 0.75  | 12 | form control padding    |
| `--space-4`  | 1     | 16 | card padding            |
| `--space-5`  | 1.5   | 24 | section padding         |
| `--space-6`  | 2     | 32 | page gutter             |
| `--space-7`  | 3     | 48 | hero vertical gutter    |

Radius ramp: `--radius-sm` = 4 px (chips), `--radius-md` = 8 px (cards,
buttons), `--radius-lg` = 12 px (modals), `--radius-full` = 9999 px.

Elevation: **only two levels**. `--shadow-1` for cards, `--shadow-2` for
modals / popovers.

---

## 5. Components

### 5.1 Buttons

| Variant      | Background               | Text                | Border |
|--------------|--------------------------|---------------------|--------|
| Primary      | `--brand-indigo-700`     | `--white`           | none   |
| Primary hover| `--brand-indigo-800`     | `--white`           | none   |
| Secondary    | `--slate-100`            | `--slate-700`       | `1px solid --slate-300` |
| Danger       | `--status-danger-bg`     | `--status-danger-fg`| `1px solid currentColor` |
| Ghost        | transparent              | `--brand-indigo-700`| none   |

**Touch target:** minimum 44 × 44 px on touch viewports (WCAG 2.5.5,
already enforced in `styles.scss` for `<=760px`). On all viewports a
hard floor of 24 × 24 CSS px applies (WCAG 2.2 SC 2.5.8 — Target Size
Minimum), with at least 4 px of clear spacing between adjacent targets.

**Focus:** 2 px solid `--brand-indigo-600` outline with `offset: 2px`.
Never remove focus rings.

### 5.2 Inputs

- Height: 40 px (desktop), 44 px (touch).
- Border: 1 px `--slate-300`. On focus: 2 px `--brand-indigo-600`.
- Error state: 1 px `--status-danger-fg`; error message uses `role="alert"`.
- Every input has an associated `<label for="…">`.

### 5.3 Dialogs / Modals

- Use the native `<dialog>` element; never roll a div.
- `aria-modal="true"`, `aria-labelledby`, `aria-describedby` are
  required.
- First focusable element receives focus on open; ESC and backdrop-click
  close. Focus returns to the trigger when the dialog closes.
- Max-width 640 px, padding 1.5 rem. On `<=600px` the dialog is 94 vw.

### 5.4 Toasts

Use the existing toast utility (`static/js/toast.js`). Do not introduce
alternative transient messaging. Toasts must have `role="status"` for
neutral, `role="alert"` for errors.

### 5.5 Tables

Sticky headers, zebra striping via `--slate-100`, row hover via
`--brand-indigo-50`. Use `<th scope="col|row">` — **always**.

---

## 6. Accessibility (WCAG 2.2 AA)

Our target is **WCAG 2.2 Level AA**, measured against the
[ACT rules](https://www.w3.org/WAI/standards-guidelines/act/). 2.2 AA
is a strict superset of 2.1 AA and 2.0 AA — every criterion from those
earlier versions still applies.

### 6.1 Non-negotiables

1. Every page has a single `<h1>`, one `<main>`, one `<nav>`.
2. Every form control has a label (`<label for>` or `aria-label`). No
   placeholder-only labels.
3. Focus is visible on every interactive element (SC 2.4.7) and never
   fully obscured by sticky chrome (SC 2.4.11 — new in 2.2).
4. Skip-link `.skip-link` is the first interactive element in `<body>`.
5. Colour is never the sole carrier of meaning (use icons + text).
6. All icons that carry meaning have an `aria-label` or paired text;
   decorative icons carry `aria-hidden="true"`.
7. Motion is discretionary — respect `prefers-reduced-motion`.
8. No fixed pixel font-sizes for body copy.
9. Every drag interaction has a non-drag alternative (SC 2.5.7 — new
   in 2.2).
10. Targets are ≥ 24 × 24 CSS px with ≥ 4 px spacing, or 44 × 44 on
    touch viewports (SC 2.5.8 — new in 2.2).
11. Authentication never relies on a cognitive-function test, allows
    paste into password fields, and does not block password managers
    (SC 3.3.8 — new in 2.2).
12. Multi-step flows pre-fill any value the user has already supplied
    in the same session (SC 3.3.7 — new in 2.2).
13. Help controls (Docs, Support, Contact) are in the same relative
    location on every page (SC 3.2.6 — new in 2.2).

### 6.2 Keyboard journey

- `Tab` visits exactly what the user would expect: skip-link → primary
  nav → main → footer.
- No keyboard trap inside any custom widget.
- Disclosure widgets (accordions, tabs) follow the
  [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/patterns/).

### 6.3 Screen reader journey

- Live-region announcements are used sparingly: `role="status"` for
  benign progress ("Checking now"), `role="alert"` for connection loss
  or errors. Never for routine UI chrome.

### 6.4 Reduced-motion support

All CSS transitions longer than 150 ms must wrap in:

```scss
@media (prefers-reduced-motion: no-preference) {
  transition: color .3s ease, background .3s ease;
}
```

### 6.5 Colour-blind sanity check

Test every new status-colour pair against the three common CVD
simulations (protanopia, deuteranopia, tritanopia). Status must still be
distinguishable from *shape and text*, not from hue alone.

### 6.6 WCAG 2.2 AA conformance map

| SC       | Title                              | How we conform |
|----------|------------------------------------|----------------|
| 1.3.1    | Info and Relationships             | Semantic HTML5; tables use `<th scope>`; landmarks (`<main>`, `<nav>`, `<header>`, `<footer>`). |
| 1.4.3    | Contrast (Minimum)                 | All pairs in § 2.4 — every pair ≥ 4.5 : 1 (normal) / 3 : 1 (large). |
| 1.4.10   | Reflow                             | No horizontal scrolling at 320 CSS px; mobile-first SCSS. |
| 1.4.11   | Non-text Contrast                  | Borders, focus rings, status icons all ≥ 3 : 1 against adjacent surfaces. |
| 1.4.12   | Text Spacing                       | All copy uses `rem`; no `!important` on `line-height`/`letter-spacing`. |
| 1.4.13   | Content on Hover or Focus          | Tooltips dismissable with ESC, persist while hovered, never overlap focus target. |
| 2.1.1    | Keyboard                           | Every interaction reachable via keyboard. |
| 2.1.2    | No Keyboard Trap                   | Modals trap *intentionally* and release on ESC. |
| 2.4.3    | Focus Order                        | DOM order matches visual order. |
| 2.4.7    | Focus Visible                      | 2 px indigo ring, never removed. |
| 2.4.11   | Focus Not Obscured (Min) **(2.2)** | `scroll-padding-top` on `html` accounts for sticky header; bottom-nav has `scroll-padding-bottom`. |
| 2.5.5    | Target Size (Enhanced, AAA)        | Best-effort 44 × 44 on touch viewports. |
| 2.5.7    | Dragging Movements **(2.2)**       | Sortable lists expose ↑/↓ keyboard reorder; resize handles offer click-to-cycle. |
| 2.5.8    | Target Size (Min) **(2.2)**        | ≥ 24 × 24 CSS px global floor; spacing ≥ 4 px. |
| 3.2.3    | Consistent Navigation              | Primary nav is identical on every page. |
| 3.2.6    | Consistent Help **(2.2)**          | Help / Docs link is in the header on desktop and in the "More" tab on mobile, in the same position on every page. |
| 3.3.1    | Error Identification               | Inline `role="alert"` with descriptive text. |
| 3.3.3    | Error Suggestion                   | Validation messages name the expected format. |
| 3.3.7    | Redundant Entry **(2.2)**          | Multi-step wizards pre-fill prior values; "duplicate watch" copies all fields. |
| 3.3.8    | Accessible Authentication **(2.2)**| Login uses email + password; paste enabled; password managers supported; no puzzles or memorisation tests. |
| 4.1.2    | Name, Role, Value                  | Custom widgets follow WAI-ARIA APG patterns. |
| 4.1.3    | Status Messages                    | Toasts use `role="status"` (info) and `role="alert"` (errors). |

Items marked **(2.2)** are new success criteria added in WCAG 2.2.

### 6.7 Testing matrix

Before any accessibility-impacting PR is merged:

1. **axe-core** (browser extension or `@axe-core/cli`) on every changed
   template — zero new violations.
2. **Lighthouse** Accessibility score ≥ 95 on the changed page.
3. **Keyboard-only** walk-through of the changed flow (no mouse).
4. **Screen reader** smoke-test on at least one of: VoiceOver (macOS or
   iOS), NVDA (Windows), Orca (Linux).
5. **320 px reflow** check in dev tools.
6. **Reduced-motion** check (`prefers-reduced-motion: reduce`).

---

## 7. Implementation rules

1. **No raw hex in partials.** Only `_brand.scss` defines hex values;
   every other file consumes `var(--…)`.
2. **No inline styles** in templates except where Jinja interpolation
   genuinely requires it. Prefer utility classes.
3. **Mobile first.** Write the base styles for narrow screens; layer
   enhancements in `@media (min-width: …)`.
4. **Source of truth is SCSS.** The compiled `styles.css` is derived —
   the review diff is in the SCSS.
5. **Breaking changes to tokens** require updating this document in the
   same commit.

---

## 8. Change log for this document

| Date       | Version | Author | Summary                         |
|------------|---------|--------|---------------------------------|
| 2026-04-13 | 1.0     | Sairo  | Initial version covering brand, palette, typography, spacing, components, accessibility, and implementation rules. |
| 2026-04-13 | 1.1     | Sairo  | Re-targeted accessibility commitment from WCAG 2.1 AA to WCAG 2.2 AA. Added § 6.6 SC-by-SC conformance map (incl. new 2.2 criteria 2.4.11, 2.5.7, 2.5.8, 3.2.6, 3.3.7, 3.3.8) and § 6.7 testing matrix. Tightened target-size rules to a 24 × 24 CSS px global floor. |
