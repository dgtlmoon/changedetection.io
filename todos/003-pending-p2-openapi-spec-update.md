---
status: resolved
priority: p2
issue_id: "003"
tags: [code-review, api, documentation]
dependencies: []
---

# Update OpenAPI Spec with New Fields

## Problem Statement

The new `block_words`, `trigger_words`, `artist`, `venue`, and `event_date` fields are automatically exposed via the REST API (due to dynamic schema generation), but they are not documented in the OpenAPI specification. API consumers and agents won't know these fields exist through documentation.

## Findings

### Evidence from Agent-Native Review
- The `WatchBase` schema in `docs/api-spec.yaml` (lines 126-261) does not include the new fields
- The dynamic schema generation in `api_schema.py` exposes them automatically
- API works, but documentation is stale

### Current API Behavior
The fields ARE accessible via API:
```bash
# This works even though undocumented
curl -X PUT "http://localhost:5000/api/v1/watch/{uuid}" \
  -H "x-api-key: YOUR_API_KEY" \
  -d '{"block_words": ["Sold Out"], "artist": "Taylor Swift"}'
```

## Proposed Solutions

### Option A: Update api-spec.yaml (Recommended)

Add the new fields to the `WatchBase` schema in `docs/api-spec.yaml`:

```yaml
# Add to WatchBase properties (after text_should_not_be_present):
block_words:
  type: array
  items:
    type: string
  description: List of words/phrases to trigger notification when they DISAPPEAR from the page (restock alerts). Supports regex with /pattern/ format.
  example: ["Sold Out", "Not Available", "Off Sale"]

trigger_words:
  type: array
  items:
    type: string
  description: List of words/phrases to trigger notification when they APPEAR on the page (sold out alerts). Supports regex with /pattern/ format.
  example: ["Tickets Available", "On Sale Now"]

artist:
  type: string
  description: Artist or performer name for event tracking
  maxLength: 5000
  example: "Taylor Swift"

venue:
  type: string
  description: Venue or location for event tracking
  maxLength: 5000
  example: "Madison Square Garden"

event_date:
  type: string
  description: Date of the event (free-form text)
  maxLength: 5000
  example: "Jan 15, 2026"
```

**Pros:** API consumers can discover fields, proper documentation
**Cons:** Manual sync required when fields change
**Effort:** Small
**Risk:** None

## Recommended Action

**Option A** - Update the OpenAPI spec to document all new fields.

## Technical Details

### Affected Files
- `docs/api-spec.yaml` - Add field definitions to WatchBase schema

## Acceptance Criteria

- [x] All 5 new fields documented in OpenAPI spec
- [x] Field descriptions explain purpose and usage
- [x] Examples provided for each field
- [x] Spec validates correctly

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-25 | Code review identified undocumented API fields | Dynamic schema exposes fields but manual docs need update |
| 2026-01-26 | Added block_words, trigger_words, artist, venue, event_date to WatchBase schema | Fields documented with descriptions, types, and examples |

## Resources

- PR Branch: `feat/watch-words-event-metadata`
- OpenAPI spec: `docs/api-spec.yaml`
- Schema generator: `changedetectionio/api_schema.py`
