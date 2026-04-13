# ADR 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering

## Context

We are starting a multi-phase rewrite (see [`../PLAN.md`](../PLAN.md)).
Decisions made at the foundation will be paid for in every later phase.
We want a lightweight, immutable record of *why* each decision was made
— not a wiki that drifts from reality.

## Decision

Adopt Architecture Decision Records (ADRs) in the format described by
Michael Nygard. Each ADR is a short Markdown file under
[`docs/saas/adr/`](.), numbered monotonically, with the sections:

- **Status** — `Proposed`, `Accepted`, `Rejected`, `Superseded by NNNN`.
- **Date** — ISO 8601.
- **Deciders** — people / team who signed off.
- **Context** — the forces at play when the decision was made.
- **Decision** — what we decided.
- **Consequences** — the good, the bad, and the obligations.

## Rules

1. ADRs are immutable once `Accepted`. To change a decision, write a new
   ADR that `Supersedes` the old one and update the old one's `Status`
   to `Superseded by NNNN`. Never edit the body of an accepted ADR.
2. ADR filenames are kebab-case: `NNNN-short-slug.md`.
3. PRs that change the scaffolded architecture must either cite an
   existing accepted ADR in the description or include a new one.

## Consequences

- A new engineer can read `docs/saas/adr/*` top-to-bottom and understand
  how the system got to its current shape without tribal knowledge.
- ADRs will occasionally disagree with live code; the living
  `phase-*.md` docs are the source of truth for "how it works *now*",
  ADRs are for "why it got that way".

## Template

Copy `0001-record-architecture-decisions.md` as a starting point.
