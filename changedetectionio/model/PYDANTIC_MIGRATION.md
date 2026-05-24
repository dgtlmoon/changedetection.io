# Pydantic Migration

Plan for incrementally moving the app's storage dicts behind Pydantic models. Driven by
security (CWE-915 mass-assignment, see [GHSA-h3x5-5j56-hm2j][advisory]) and schema
enforcement, not just type tidying.

[advisory]: https://github.com/dgtlmoon/changedetection.io/security/advisories/GHSA-h3x5-5j56-hm2j

## The goal

Every form/API endpoint that mutates a stored dict should validate input against a
declared schema before writing. `extra='forbid'` rejects unknown keys — so an attacker
POSTing extra fields like `uuid=…`, `last_checked=…`, `history=[…]` can't smuggle them
into storage. Per-route allowlists work but rot; one declared schema per stored shape
doesn't.

## Prefer a migration over permanent complexity

If you're about to add a compatibility shim, an alias, a backward-compat fallback, or a
"handle both old and new shape" branch — stop and ask whether a one-time `update_N`
migration solves the same problem by *renaming the stored data*. A migration runs once
per install; the shim lives in the code forever and every future contributor has to
understand it.

Concrete example from this PR: the original design used `Field(alias='llm_X')` so
Pydantic could accept both the legacy form-field name (`llm_model`) and the new
storage name (`model`). That alias survived every read/write for the life of the app
and introduced a subtle `model_dump(by_alias=True)` merge bug. The simpler answer was
to rename the form fields to match the storage names (an in-PR rename, no migration
needed since storage was new), drop the aliases entirely, and delete ~25 lines of
plumbing. **Pay once with a migration; don't pay forever with complexity.**

Same principle applies the moment you find yourself writing `dict.get(new_key) or
dict.get(old_key)`. That's a migration in disguise — write the migration instead.

## Architecture choice: validator at the boundary, not domain model

There are two ways to use Pydantic. Pick one per slice — they are not interchangeable.

**Pydantic-as-validator (what we do).** Storage stays a plain dict. A `BaseModel`
validates input at the boundary, dumps back to a dict. No call-site changes; the
existing `watch['x']` dict access keeps working everywhere.

**Pydantic-as-domain-model.** Replace `dict` inheritance with `BaseModel`. ~190 call
sites switch from `watch['x']` to `watch.x`. Much bigger blast radius, defers the
security win. Not what we're doing right now.

The CWE-915 fix only needs the validator pattern. Domain-model replacement is a
separate, later project.

## The template (LLMSettings)

The first migrated slice. Use as the reference for the next one.

**Match the WTForms field names to the storage / Pydantic field names** so the
form-input dict and the storage dict have the same key shape. No aliases, no
`populate_by_name=True`, no `by_alias=True` merge gymnastics. Only reach for
`Field(alias=…)` if you genuinely cannot rename the form field (rare).

`model/LLMSettings.py`:

```python
class LLMSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool = True
    model: str = ''
    ...

    # System-managed counters
    tokens_total_cumulative: int = 0
    ...

    # Field groups
    CONNECTION_FIELDS: ClassVar[Tuple[str, ...]] = ('model', 'api_key', ...)
    PROTECTED_FIELDS:  ClassVar[Tuple[str, ...]] = ('tokens_total_cumulative', ...)
```

Boundary pattern at the route handler:

```python
# Read
settings = LLMSettings.model_validate(
    datastore.data['settings']['application'].get('llm') or {}
)

# Merge form input
form_input = dict(form.data.get('llm') or {})
for protected in LLMSettings.PROTECTED_FIELDS:
    form_input.pop(protected, None)  # counters never come from form
merged = LLMSettings.model_validate({**settings.model_dump(), **form_input})

# Write — re-validates the schema on every write
datastore.data['settings']['application']['llm'] = merged.model_dump()
```

## Unresolved architectural decisions

Two decisions need answers before the `WatchInput` slice. They're not blockers for `App.py`.

### OpenAPI spec vs Pydantic model — who's source of truth?

Today: `docs/api-spec.yaml` declares the Watch/Tag shape; `model/schema_utils.py` reads
it to compute readonly fields; the API layer validates against it; the model layer is a
plain dict that doesn't know about either. When `WatchInput` lands, that's a third
shape declaration.

Two ways to live:
- **Pydantic is source.** Generate / sync `api-spec.yaml` from the model
  (e.g. via `model_json_schema()`). One declaration, multiple consumers. Long-term
  right answer; needs tooling.
- **Parallel sources with discipline.** Hand-keep them aligned. Faster to ship but
  drift is inevitable — that's the bug class we're already trying to close.

Recommendation: start parallel (keep `api-spec.yaml` for now), but write Watch's
Pydantic model so it could be the eventual single source. Don't *invent* a new
field shape — match the spec.

### Plugin / processor_config_* extensibility

`processor_config_restock_diff` (and future processor configs) are written by
plugins, not the core. `extra='forbid'` on a Watch input model would reject them.

Options:
- **Per-processor sub-models.** Each plugin owns its `<Processor>Settings` Pydantic
  model; Watch input validates only core fields, processor configs validate
  separately at their own boundary (the per-watch `restock_diff.json`, etc.).
- **Opaque pass-through.** Watch input model treats `processor_config_*` as a
  declared dict-typed field. Loses per-key validation but preserves the
  plugin-extensibility contract.

Recommendation: per-processor sub-models. Matches the file split already done in
`update_30` (separate `restock_diff.json` per watch).

## Migration order

| Target | Difficulty | Value | Status |
|---|---|---|---|
| `LLMSettings` | low | medium | done (this PR) |
| `App.py` → `AppSettings` (nested) | low | medium | next |
| `WatchInput` (form/API validator) | medium | **HIGH — closes [GHSA-h3x5-5j56-hm2j][advisory]** | next-next |
| `TagInput` (form/API validator) | medium | medium | after Watch |
| `watch_base(dict)` → `BaseModel` | very high | high | separate multi-PR project, much later |

`Tags.py` (TagsDict), `persistence.py`, `schema_utils.py` are not data models — leave alone.

### Concrete next steps

1. **`App.py`.** Pure dict tree under `settings.{application,requests,headers}`. Define
   nested `BaseModel`s; `LLMSettings` slots in as the existing sub-tree. No call-site
   churn — just the global settings POST handler. Sets the pattern for nested models.

2. **`WatchInput` BaseModel** for `blueprint/ui/edit.py:225` and `api/Watch.py`. Replace:
   ```python
   datastore.data['watching'][uuid].update(form.data)  # CWE-915
   ```
   with:
   ```python
   validated = WatchInput.model_validate(form.data)
   datastore.data['watching'][uuid].update(validated.model_dump())
   ```
   Closes the unpatched advisory. Should be a security-tagged commit referencing the GHSA.

3. **`TagInput` BaseModel** — same pattern, smaller.

## Gotchas discovered

These cost real debugging time in the LLMSettings PR. Worth knowing before the next slice.

### `extra='forbid'` is the right default

`extra='ignore'` silently drops unknowns and hides developer mistakes (add a form field,
forget to declare it on the model, your feature appears to work until you reload). `forbid`
fails loudly. `allow` defeats the purpose entirely — it's how injection succeeds.

### Don't use Field aliases unless you actually need them

The LLMSettings PR originally used `alias='llm_X'` to bridge llm_-prefixed WTForms
names to stripped storage names. That created a documented gotcha: with
`extra='forbid'`, having both `model` and `llm_model` in the same input dict is a
`ValidationError`, and merging existing-storage-dump with form input required
`by_alias=True` to keep both sides on the alias shape. We fixed it by renaming the
form fields to match the storage field names. **Match the form to the model
upfront and you avoid the whole class of merge bugs.**

### Round-trip counters through the model, don't mutate the dict

If runtime code (e.g. a token accumulator) writes to the storage dict directly, the
schema is bypassed. Load → mutate instance attributes → `model_dump()` → write back.
This re-validates on every write and prevents drift.

### Per-call validation needs strict + tolerant modes? Don't.

You might be tempted to validate form input strictly but allow extras in storage
hydration. Don't — `extra='forbid'` everywhere means storage drift is impossible. If
something put unknown keys in storage, you want loud failure, not silent acceptance.

### Migrations are convention-based by accident if you let them be

`for k in list(d) if k.startswith('llm_')` is shorter than an explicit list but
silently catches any future flat `llm_*` key. Migrations are forever — prefer an
explicit allowlist of keys to move, even if it's verbose.

## What NOT to do

- Don't add custom helper methods (`dump_without_connection()`, `clear_X()`) when stock
  `model_dump(exclude=set(FIELDS))` works. The standard idiom is more readable and
  zero-line.
- Don't push security/business logic into the model (e.g. SSRF guards, credential-exfil
  checks). The model owns field shape and validation. Route handlers own
  policy. Mixing them dilutes both.
- Don't make `get_X_config()` return a Pydantic instance if callers do dict-style access.
  Either migrate all call sites (high-touch) or keep returning a dict and let the model
  be the validation/dump layer only.
- Don't `model_copy(update=...)` without re-validating. It doesn't coerce types or
  enforce `extra='forbid'`. Use `model_validate({**old.model_dump(), **updates})` for
  strict merges.

## Required for each new slice

Each migration PR should ship:

- `model/<Thing>Settings.py` (or input model) — declared schema, `extra='forbid'`,
  field aliases if there's a name mismatch between form and storage.
- `store/updates.py:update_N` if the storage shape changes. Pure dict-shuffling, no
  Pydantic import (migrations should not depend on the model — model evolves
  independently).
- `tests/unit/test_<thing>.py` — unit coverage of the model itself: defaults,
  alias merge, type coercion, `extra='forbid'` rejection, dump shapes.
- All runtime callers updated to go through `get_<thing>_settings(datastore)` or
  equivalent, not raw dict reads.

## Reference

- `model/LLMSettings.py` — the template
- `tests/unit/test_llm_settings.py` — model unit-test template
- `store/updates.py:update_31` — schema migration template
- `blueprint/settings/__init__.py` (POST handler) — boundary-validation template
- `llm/evaluator.py:accumulate_global_tokens` — instance-mutation-then-dump-back template
