# ADR 0007 — Lemon Squeezy as Merchant of Record for launch

- **Status:** Accepted
- **Date:** 2026-04-13
- **Deciders:** Sairo engineering
- **Decision reference:** D6 in [`../decisions.md`](../decisions.md)

## Context

Three billing vendors are realistic:

1. **Stripe** — direct, most features, most flexibility. **We** are
   Seller of Record — we collect VAT/sales tax worldwide, file returns,
   and handle chargebacks.
2. **Lemon Squeezy** — Merchant of Record. They handle VAT/sales tax
   globally, chargebacks, invoicing, customer support on billing
   questions. Slightly higher per-transaction fee.
3. **Paddle** — similar MoR model, different pricing, different API.

At ≤$5M ARR, the tax / compliance overhead of being Seller of Record
is a full-time accounting job. That's more than the per-transaction
fee differential.

## Decision

**Lemon Squeezy for launch.** Build the billing adapter behind a
`BillingProvider` interface so swapping to Stripe later (when scale
justifies it) is a bounded refactor, not a rewrite.

- Checkout is hosted by Lemon Squeezy.
- Webhooks land at `services/billing/` and are signature-verified.
- Subscriptions, invoices, and customer-portal links are consumed via
  the Lemon Squeezy REST API.
- The `BillingProvider` interface exposes only what the rest of the app
  needs: `create_checkout_url(org, plan) → str`, `get_subscription(org) →
  Subscription`, `sync_from_webhook(event) → None`, `portal_url(org) → str`.

## Consequences

**Good**
- No VAT / sales-tax burden at launch.
- Faster path to revenue.
- Chargebacks are Lemon Squeezy's problem.

**Bad**
- Higher per-transaction fee than Stripe.
- Customer-visible entity on credit-card statements is Lemon Squeezy,
  not Sairo — a small branding concern for enterprise buyers.
- Lemon Squeezy's API is less complete than Stripe's; some advanced
  flows (usage-based metering, flexible prorations) need workarounds.

**Obligations**
- All billing code talks to the `BillingProvider` interface, not the
  Lemon Squeezy SDK directly. No vendor name appears outside
  `services/billing/providers/lemonsqueezy.py`.
- Quota enforcement is local (in our DB), not driven by webhook arrival
  — webhooks confirm state, they don't drive it. This keeps us
  swap-safe.
- We revisit this decision when either (a) ARR exceeds $5M, or (b) a
  specific customer class demands Stripe as seller of record.
