# Phase 3 — New data layer

> Status: **draft.** This is the ceiling-setter: the shapes chosen here
> determine what every subsequent phase can do. Nothing here is built
> yet.

## Goal

Replace [`changedetectionio/store/file_saving_datastore.py`](../../changedetectionio/store/file_saving_datastore.py)
with a Postgres-backed, tenant-scoped store and move binary artefacts
(snapshots, screenshots, PDFs, favicons) to S3-compatible object
storage. Do it behind a `NEW_STORE=true` feature flag so the existing
single-tenant store keeps working until the switch.

## Architectural decisions

### The `Store` interface

A new abstract interface the rest of the code talks to. Two concrete
implementations during the migration:

| Impl | Used when | Notes |
|---|---|---|
| `FileStore` | `NEW_STORE=false` (default for legacy) | Wraps the existing `ChangeDetectionStore` unchanged |
| `PgStore` | `NEW_STORE=true` (SaaS, new self-hosted) | Postgres + object storage |

Every caller that today does `datastore.data['watching'][uuid]['url']`
goes through `store.watches.get(org_id, uuid).url`. That's the one-time
big refactor.

### Data shapes

Direct port of the existing model fields — no feature regressions — with
`org_id` added everywhere.

| Table | Maps from (legacy) | Notes |
|---|---|---|
| `watches` | `model/Watch.py` | ~50 JSON fields flattened to columns where cheap (`url`, `title`, `tags`, `paused`, `last_checked`, …); keep the long-tail fetcher/filter config as a `jsonb settings` column |
| `watch_tags` | `model/Tag.py` | Tag is per-org; `watch_tag_links` m2m join |
| `watch_history_index` | `history.txt` | One row per snapshot: `watch_id`, `taken_at`, `content_type`, `object_key`, `size_bytes`, `hash_md5` |
| `watch_notification_targets` | inline on `Watch` | Per-watch Apprise URLs; globals live on `orgs.notification_settings` jsonb |
| `proxies` | `proxies.json` | Per-org list of proxy URLs |
| `org_settings` | `settings.application` | jsonb blob of per-org tunables (was global) |

### Binary artefacts

All non-tabular data → object storage. Key scheme:

```
s3://onchange-data/{org_id}/watches/{watch_id}/snapshots/{iso8601}.brotli
s3://onchange-data/{org_id}/watches/{watch_id}/screenshots/{iso8601}.jpg
s3://onchange-data/{org_id}/watches/{watch_id}/pdfs/{iso8601}.pdf
s3://onchange-data/{org_id}/watches/{watch_id}/favicon.{ext}
s3://onchange-data/{org_id}/watches/{watch_id}/browser_steps/{step_id}_{timestamp}.jpg
```

Org-prefix in the key enforces isolation even at the IAM level — an
IAM policy can restrict a per-org credential to `{org_id}/*`.

Storage-class rules: hot for the last 90 days, lifecycle-transitioned to
Infrequent Access after that. Screenshots are the big cost centre.

### Favicon cache

The module-level dict at [`changedetectionio/model/Watch.py:49`](../../changedetectionio/model/Watch.py)
becomes a Redis hash: `favicon:{org_id}:{watch_id}` → base64 bytes, 24-h
TTL.

### Processors & fetchers

The processor function signatures stay:
```python
def run_changedetection(watch, skip_when_checksum_same=True): ...
```
but `watch` becomes an ORM object with the same attribute shape as the
legacy dict (SQLAlchemy declarative + `__getitem__` for back-compat
during the cutover).

Processors that today mutate the global datastore (`datastore.data[...]`)
get their call sites rewritten to return a dict of updates that the
worker applies through `store.watches.apply(...)`. The processors
themselves become purer — easier to test, trivially parallel.

Expected touch surface:

| File | Change |
|---|---|
| `changedetectionio/store/__init__.py` | Extract `StoreProtocol`; keep legacy impl |
| `changedetectionio/store/pg.py` *(new)* | `PgStore` implementation |
| `changedetectionio/store/object_storage.py` *(new)* | S3 adapter (boto3 or aiobotocore) |
| `changedetectionio/model/Watch.py` | Add `_from_row(row)` / `_to_row()`; make `__getitem__` forward to attrs |
| `changedetectionio/processors/*/processor.py` | Return updates instead of mutating; remove `datastore` imports |
| `changedetectionio/content_fetchers/*.py` | Take screenshot/body byte-returns; caller writes to object storage |
| `services/core/` *(new)* | FastAPI router that exposes the new tenant-scoped API consuming `PgStore` |

### Migration from legacy datastore

`scripts/import_legacy_datastore.py`:

```bash
python scripts/import_legacy_datastore.py \
    --source /path/to/old/datastore \
    --org-slug acme \
    --dry-run
```

Steps the importer takes:

1. Validate the target org exists.
2. Parse `changedetection.json` → `org_settings` jsonb for that org.
3. For each `{uuid}/watch.json` → insert `watches` row with `org_id`.
4. For each snapshot in `history.txt` → upload to object storage, insert
   a `watch_history_index` row.
5. Upload screenshots, favicons, PDFs, browser-steps images.
6. Write an `audit_logs` entry `{action: 'org.import.complete',
   metadata: { source_path, watches: N, bytes: M }}`.

Importer is **idempotent**: re-running with the same source + org is a
no-op if checksums match. Keeps the old datastore untouched on disk for
≥30 days so rollback is a flag flip, not a restore.

## Risks specific to Phase 3

| Risk | Mitigation |
|---|---|
| Processors silently depend on `datastore` as a singleton | A pre-Phase-3 audit PR strips every `from changedetectionio import datastore` and makes it an explicit function argument. This is a blocker; if the audit shows deep coupling in 5+ files the scope grows. |
| `jsonb settings` becomes a kitchen sink | Every new column we add to `jsonb` gets a migration comment; quarterly review surfaces fields worth promoting to columns |
| Cost blowup from object storage listing | Never `LIST` at runtime; the `watch_history_index` table is the authoritative listing |
| Snapshot hot-path latency regresses | Benchmark: snapshot write p95 must stay under 200 ms after the move; if not, batch writes through a Redis stream |
| Cross-tenant object key collision | Org-prefixed keys + IAM scoping prevents code-level bugs from becoming data-leak bugs |

## Done-when checklist

- [ ] `StoreProtocol` interface + `FileStore` + `PgStore` implementations.
- [ ] Alembic migration for `watches`, `watch_tags`, `watch_tag_links`,
  `watch_history_index`, `watch_notification_targets`, `proxies`,
  `org_settings`. All with RLS.
- [ ] Object-storage adapter with presigned-URL helper.
- [ ] Importer with dry-run + checksum idempotency.
- [ ] Every existing processor test passes under `NEW_STORE=true`.
- [ ] Cross-tenant isolation tests: a worker running for org A cannot
  read org B's snapshots even with a crafted path.
- [ ] p95 benchmark for snapshot write, snapshot read, watch list.
- [ ] Self-hosted Coolify compose updated to bundle Postgres + Redis
  with a one-shot `alembic upgrade head` entrypoint.
