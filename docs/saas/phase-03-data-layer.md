# Phase 3 — New data layer

> Status: **3.1 landing now.** 3.2 + 3.3 planned, built after 3.1
> is merged.

## Goal

Replace [`changedetectionio/store/file_saving_datastore.py`](../../changedetectionio/store/file_saving_datastore.py)
with a Postgres-backed, tenant-scoped store and move binary artefacts
(snapshots, screenshots, PDFs, favicons) to S3-compatible object
storage. Do it behind a `NEW_STORE=true` feature flag so the existing
single-tenant store keeps working until the switch.

## Sub-phase split

| # | Scope | Status |
|---|---|---|
| **3.1** | `services/core/` scaffold; `WatchStore` + `TagStore` protocols; Postgres-backed implementation; watches + watch_tags + watch_tag_links tables; RLS; CRUD + cross-tenant tests. **No HTTP routes.** | **landing now** |
| 3.2 | Object-storage adapter (S3-compatible), `watch_history_index` table, snapshots + screenshots + favicon persistence, importer from the legacy file datastore. | pending |
| 3.3 | Processor rewiring: remove singleton `datastore` imports, processors return updates instead of mutating, side-by-side tests under both stores, `NEW_STORE` feature flag cutover. | pending |

The 3.1 / 3.2 / 3.3 order is enforced — 3.2 needs 3.1's tables to
index history into, and 3.3 needs both stores before it can compare
behaviour.

---

## 3.1 — Core store + schema (this commit)

### New service: `services/core/`

Owns the tenant-scoped watch API that will eventually replace the
Flask blueprints in `changedetectionio/blueprint/`. For 3.1 we only
need the package and its DB layer — HTTP routes come in a later PR.

```
services/core/
├── pyproject.toml
├── alembic.ini           # version_table = alembic_version_core
├── README.md
├── migrations/
│   └── versions/
│       └── 20260413_0001_watches_tags.py
├── app/
│   ├── config.py
│   ├── db.py             # its own engine + with_current_org()
│   ├── models/           # watch, watch_tag, watch_tag_link
│   └── store/
│       ├── protocol.py   # WatchStore, TagStore
│       └── pg.py         # PgWatchStore, PgTagStore
└── tests/
    ├── conftest.py
    ├── test_watches_crud.py
    └── test_tags_crud.py
```

### Migration ordering

Core depends on identity's `orgs` table (`watches.org_id` references
`orgs.id`). The two services each manage their own migration tree
with a distinct `version_table`:

- identity uses the default `alembic_version`.
- core uses `alembic_version_core`.

Both connect to the same database. Deploy order:
`alembic upgrade head` in **identity first**, then in core. CI
enforces this.

### Table: `watches`

High-value fields get real columns; the long tail stays in `settings`
jsonb so the 120+ legacy `Watch.model` fields don't multiply the
migration burden.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | `uuid7()` |
| `org_id` | `uuid` not null FK → `orgs.id` | RLS key |
| `url` | `text` not null | |
| `title` | `text` nullable | |
| `processor` | `text` not null default `'text_json_diff'` | |
| `fetch_backend` | `text` not null default `'system'` | |
| `paused` | `bool` not null default false | |
| `notification_muted` | `bool` not null default false | |
| `time_between_check_seconds` | `int` nullable | null = use org default |
| `last_checked` | `timestamptz` nullable | |
| `last_changed` | `timestamptz` nullable | |
| `last_error` | `text` nullable | |
| `check_count` | `bigint` not null default 0 | |
| `previous_md5` | `text` nullable | |
| `settings` | `jsonb` not null default `'{}'` | everything else |
| `created_at`, `updated_at`, `deleted_at` | `timestamptz` | |

Indexes:
- `(org_id, deleted_at)` partial — fast org list
- `(org_id, paused)` — scheduler queries unpaused watches
- `(org_id, last_checked ASC NULLS FIRST)` — scheduler ordering

### Table: `watch_tags`

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `org_id` | `uuid` not null FK | |
| `name` | `citext` not null | |
| `color` | `text` nullable | |
| `settings` | `jsonb` not null default `'{}'` | tag overrides |
| `created_at`, `updated_at`, `deleted_at` | `timestamptz` | |

Unique `(org_id, name)` partial index `WHERE deleted_at IS NULL`.

### Table: `watch_tag_links`

Simple m2m. Composite PK `(watch_id, tag_id)`. Both FKs
`ON DELETE CASCADE`.

### RLS

Enabled on all three tables. `watch_tag_links` has no direct
`org_id`; its policy joins to `watches`:

```sql
CREATE POLICY p_watch_tag_links_org_isolation ON watch_tag_links
    USING (EXISTS (
        SELECT 1 FROM watches w
        WHERE w.id = watch_tag_links.watch_id
          AND w.org_id = NULLIF(current_setting('app.current_org', true), '')::uuid
    ));
```

### `WatchStore` / `TagStore` protocols

`typing.Protocol` — no full ABC needed. Concrete implementations take
`AsyncSession` as first argument (same pattern identity uses) so
tests can inject freely. Every method takes `org_id` explicitly and
filters on it in the ORM query AND runs under
`with_current_org(org_id)` — belt + suspenders.

### Done-when checklist (3.1)

- [x] `services/core/` scaffold compiles; `uv run pytest` passes.
- [x] Alembic migration forward + `downgrade base` reversible.
- [x] `PgWatchStore` + `PgTagStore` full CRUD tests @db.
- [x] Cross-tenant isolation: org A cannot read / update / delete
  org B's watches or tags via the store.
- [x] `assign_to_watch` m2m tests (add, remove, cross-tenant tag
  ignored).
- [x] CI job for core service runs after identity migrations.
- [ ] *(3.2)* HTTP routes.
- [ ] *(3.2)* Object storage + history index + importer.
- [ ] *(3.3)* Legacy processor rewiring + cutover flag.

---

## 3.2 — Object storage, history index, HTTP routes, legacy importer

> Status: **3.2a landing now** (history index + object storage).
> 3.2b (HTTP routes) and 3.2c (legacy importer) are separate PRs.

### 3.2a — History index + object storage

New table `watch_history_index`, one row per persisted artefact
(snapshot text, screenshot, PDF, browser-step image). The row points
at a key in object storage; the blob itself never touches Postgres.

| Column | Type | Notes |
|---|---|---|
| `id` | `uuid` PK | |
| `watch_id` | `uuid` not null FK → `watches.id` ON DELETE CASCADE | tenant boundary via the FK chain |
| `taken_at` | `timestamptz` not null | logical capture time |
| `kind` | `text` not null | `snapshot` / `screenshot` / `pdf` / `browser_step` |
| `content_type` | `text` not null | MIME |
| `object_key` | `text` not null unique | `org_id/watches/watch_id/…` |
| `size_bytes` | `bigint` not null | quotas + UI |
| `hash_md5` | `text` not null | checksum; importer uses it for idempotency |
| `created_at` | `timestamptz` | |

Indexes:
- `(watch_id, taken_at DESC)` — the main paginate-history query.
- `(watch_id, kind, taken_at DESC)` — filter by artefact type.
- unique `(object_key)` — prevents collisions from concurrent imports.

RLS: `EXISTS`-join to `watches` (same pattern as `watch_tag_links`).

### Object storage

```
services/core/app/object_store/
├── protocol.py   # ObjectStore Protocol
├── local.py      # LocalObjectStore — filesystem, dev + tests
└── s3.py         # S3ObjectStore — aioboto3, prod
```

Key scheme (enforced by callers, not the protocol):

```
{org_id}/watches/{watch_id}/snapshots/{iso8601}.brotli
{org_id}/watches/{watch_id}/screenshots/{iso8601}.jpg
{org_id}/watches/{watch_id}/pdfs/{iso8601}.pdf
{org_id}/watches/{watch_id}/favicon.{ext}
{org_id}/watches/{watch_id}/browser_steps/{step_id}_{iso8601}.jpg
```

`LocalObjectStore` refuses keys containing `..` or leading `/` so a
malicious watch URL can't traverse outside its sandbox.

`S3ObjectStore` uses the standard AWS SDK env vars (or an explicit
credentials pair). In production the IAM policy on that credential
restricts the bucket to a given prefix, so even a code bug cannot
reach another tenant's blobs.

### `PgHistoryStore`

```python
class HistoryStore(Protocol):
    async def record(self, db, *, watch_id, taken_at, kind,
                     content_type, object_key, size_bytes,
                     hash_md5) -> WatchHistoryEntry: ...
    async def list(self, db, *, watch_id, limit=50, offset=0,
                   kind=None) -> list[WatchHistoryEntry]: ...
    async def get(self, db, *, watch_id, entry_id) -> WatchHistoryEntry | None: ...
    async def delete(self, db, *, watch_id, entry_id) -> tuple[bool, str | None]: ...
```

`delete` returns `(deleted, object_key)` so the caller can remove the
blob from object storage in a second step — DB first, blob second, so
a blob-delete failure leaves a row we can GC rather than the reverse.

### Done-when (3.2a)

- [x] `watch_history_index` table + RLS + reversibility CI.
- [x] `LocalObjectStore` works against a tmp directory; path-traversal
  guard has a test.
- [x] `S3ObjectStore` compiles and has a unit-level interface test.
- [x] `PgHistoryStore` CRUD + cross-tenant isolation tests.
- [ ] *(3.2b)* HTTP routes under `services/core/`.
- [ ] *(3.2c)* Legacy importer.

---

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
