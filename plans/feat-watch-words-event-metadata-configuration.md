# Feature: Watch Words & Event Metadata (Simplified)

## Overview

Add easy-to-use watch word configuration and event metadata fields. Users configure "block words" (notify when word disappears - restock alerts) and "trigger words" (notify when word appears - sold out alerts). Event metadata (artist, venue, date) can be entered manually.

## Problem Statement

The existing `text_should_not_be_present` and `trigger_text` fields have confusing names. Event metadata fields exist in Quick Event form but don't persist properly to the watch model.

## Proposed Solution

### Simple Data Model

Add two straightforward list fields for watch words:

```python
# In watch_base model
'block_words': [],    # Notify when these words DISAPPEAR (restock alerts)
'trigger_words': [],  # Notify when these words APPEAR (sold out alerts)

# Event metadata
'artist': None,
'venue': None,
'event_date': None,
```

That's it. No domain templates (use existing tags for grouping). No per-word settings. No CSS selector extraction (manual entry only).

### Use Existing Infrastructure

- **For grouping watches by domain**: Use the existing tag system. Create a "Ticketmaster" tag with default watch words.
- **For text matching**: Extend existing `RuleEngine` in `processors/text_json_diff/processor.py`
- **For UI patterns**: Use existing `StringListField` (one word per line textarea)

## Acceptance Criteria

### Watch Words
- [x] Can add block_words (notify when disappears) via textarea
- [x] Can add trigger_words (notify when appears) via textarea
- [x] Words support regex using existing `/pattern/` format
- [x] Case-insensitive matching by default
- [x] Matched status shown on diff page (which words matched)

### Event Metadata
- [x] Manual entry fields for: artist, venue, event_date
- [x] Fields persist to watch model
- [x] Fields editable from standard edit form
- [x] Fields visible in watch list/detail views

### UX Improvements
- [x] Better labels: "Notify when DISAPPEARS" / "Notify when APPEARS"
- [x] Help text explaining each field's behavior
- [x] Watch words and event metadata in same edit tab

## Implementation

### Phase 1: Data Model & Core Logic

**File: `changedetectionio/model/__init__.py`**

Add to `watch_base` (around line 65):

```python
'block_words': [],      # Notify when these words disappear
'trigger_words': [],    # Notify when these words appear
'artist': None,
'venue': None,
'event_date': None,
```

**File: `changedetectionio/processors/text_json_diff/processor.py`**

Extend `RuleEngine` class to evaluate block_words and trigger_words using existing `strip_ignore_text()` logic from `html_tools.py`.

### Phase 2: Forms & Edit UI

**File: `changedetectionio/forms.py`**

Add to `processor_text_json_diff_form`:

```python
block_words = StringListField(
    'Notify when DISAPPEARS',
    validators=[ValidateListRegex()],
    render_kw={"placeholder": "Sold Out\nNot Available\nOff Sale"}
)

trigger_words = StringListField(
    'Notify when APPEARS',
    validators=[ValidateListRegex()],
    render_kw={"placeholder": "Tickets Available\nOn Sale Now"}
)

artist = StringField('Artist')
venue = StringField('Venue')
event_date = StringField('Event Date', render_kw={"placeholder": "Jan 15, 2026"})
```

**File: `changedetectionio/templates/edit.html`**

Add "Event & Watch Words" section to the Filters & Triggers tab:

```html
<fieldset>
  <legend>Watch Words</legend>
  {{ render_field(form.block_words) }}
  <p class="help">Enter words/phrases (one per line). You'll be notified when these DISAPPEAR from the page (e.g., "Sold Out" disappearing = tickets available).</p>

  {{ render_field(form.trigger_words) }}
  <p class="help">Enter words/phrases (one per line). You'll be notified when these APPEAR on the page.</p>
</fieldset>

<fieldset>
  <legend>Event Details (Optional)</legend>
  {{ render_field(form.artist) }}
  {{ render_field(form.venue) }}
  {{ render_field(form.event_date) }}
</fieldset>
```

### Phase 3: Display on Check Results

**File: `changedetectionio/blueprint/ui/templates/diff.html`**

Add section showing:
- Configured watch words
- Which words matched (if any)
- Event metadata (artist, venue, date)

**File: `changedetectionio/blueprint/ui/preview.py`**

Pass watch word match results to template.

## Common Watch Word Examples

Document these in help text or tooltips:

**Block Words (notify when disappears = restock alert):**
```
Sold Out
Not Available
Unavailable
Off Sale
No Tickets
Event Cancelled
```

**Trigger Words (notify when appears = sold out alert):**
```
Sold Out
Sale Ended
Tickets Unavailable
```

## What's NOT in Scope

Based on reviewer feedback, these are explicitly deferred:

1. **Domain Templates** - Use existing tags for grouping watches by domain
2. **CSS Selector Extraction** - Manual entry only; auto-extraction is a separate feature
3. **Per-word settings** (case sensitivity, behavior) - Keep it simple with two lists
4. **Context highlighting** - Just show matched yes/no, not surrounding text
5. **WatchWordsProcessor class** - Extend existing RuleEngine instead

## Migration

Existing `text_should_not_be_present` and `trigger_text` fields continue to work. The new fields are additive. In the UI, consider:
- Showing old fields as "Legacy" with suggestion to use new fields
- Or migrating old field values to new fields on first edit

## Files to Modify

| File | Changes |
|------|---------|
| `changedetectionio/model/__init__.py` | Add 5 fields to watch_base |
| `changedetectionio/forms.py` | Add StringListFields and event fields |
| `changedetectionio/processors/text_json_diff/processor.py` | Extend RuleEngine |
| `changedetectionio/templates/edit.html` | Add form section |
| `changedetectionio/blueprint/ui/templates/diff.html` | Add display section |
| `changedetectionio/blueprint/ui/preview.py` | Pass match results |

## Estimated Effort

- Phase 1: Model + processor changes - small
- Phase 2: Forms + edit UI - small
- Phase 3: Display changes - small

**Total: Can ship in 1-2 days, not 5 phases.**

## References

- Existing text matching: `changedetectionio/html_tools.py:461-526`
- RuleEngine: `changedetectionio/processors/text_json_diff/processor.py:168-223`
- StringListField: `changedetectionio/forms.py:66-87`
- Tag system (for grouping): `changedetectionio/blueprint/tags/__init__.py`
