---
status: resolved
priority: p3
issue_id: "004"
tags: [code-review, security, validation]
dependencies: []
---

# Add Input Length Validation to Event Metadata Fields

## Problem Statement

The `artist`, `venue`, and `event_date` form fields have no maximum length constraints. While not a direct security vulnerability (XSS is prevented by autoescaping), extremely large inputs could cause storage bloat and UI rendering issues.

## Findings

### Evidence from Security Review
Location: `changedetectionio/forms.py` (lines 891-893)

```python
artist = StringField(_l('Artist'), [validators.Optional()])
venue = StringField(_l('Venue'), [validators.Optional()])
event_date = StringField(_l('Event Date'), [validators.Optional()], render_kw={"placeholder": "Jan 15, 2026"})
```

### Existing Pattern
Other string fields in the codebase (e.g., `title`) also lack length validation, so this follows existing (imperfect) patterns.

## Proposed Solutions

### Option A: Add Length Validators (Recommended)

```python
artist = StringField(_l('Artist'), [validators.Optional(), validators.Length(max=500)])
venue = StringField(_l('Venue'), [validators.Optional(), validators.Length(max=500)])
event_date = StringField(_l('Event Date'), [validators.Optional(), validators.Length(max=100)], render_kw={"placeholder": "Jan 15, 2026"})
```

**Pros:** Defense in depth, prevents abuse
**Cons:** Minor code change
**Effort:** Small
**Risk:** None

## Recommended Action

**Option A** - Add reasonable length validators as defense-in-depth.

## Technical Details

### Affected Files
- `changedetectionio/forms.py` - Add validators.Length() to fields

## Acceptance Criteria

- [x] artist field has max length 500
- [x] venue field has max length 500
- [x] event_date field has max length 100
- [x] Form validation rejects oversized inputs with helpful error message

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-25 | Security review recommended length validation | Defense-in-depth improvement |
| 2026-01-26 | Added validators.Length() to both QuickEventForm and processor_text_json_diff_form | Also added length validation to event_time field |

## Resources

- PR Branch: `feat/watch-words-event-metadata`
