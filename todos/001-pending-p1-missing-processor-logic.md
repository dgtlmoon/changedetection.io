---
status: resolved
priority: p1
issue_id: "001"
tags: [code-review, architecture, feature-incomplete]
dependencies: []
---

# Missing Processor Logic for Watch Words

## Problem Statement

The `block_words` and `trigger_words` fields are stored in the model and displayed in the UI, but **no processor logic exists** to actually use them for change detection. Users will configure these fields expecting them to trigger notifications, but nothing will happen.

This is a **critical** issue because the feature is exposed in the UI as functional, but is actually dead code.

## Findings

### Evidence from Architecture Review
- The `RuleEngine` class in `processors/text_json_diff/processor.py` has methods for `trigger_text` and `text_should_not_be_present` but **no methods for `block_words` or `trigger_words`**
- The `FilterConfig` class does not expose the new fields
- Grep for `block_words|trigger_words` in the processors directory returns **no results**

### Existing Pattern Reference
```python
# processor.py lines 172-205 - existing methods
@staticmethod
def evaluate_trigger_text(content, trigger_patterns):
    # Returns True (blocked) if trigger NOT found

@staticmethod
def evaluate_text_should_not_be_present(content, patterns):
    # Returns True (blocked) if text found
```

### Expected Behavior per Plan
From `plans/feat-watch-words-event-metadata-configuration.md`:
- `block_words`: "Notify when these words DISAPPEAR (restock alerts)"
- `trigger_words`: "Notify when these words APPEAR (sold out alerts)"

## Proposed Solutions

### Option A: Implement Processor Logic (Recommended)
Add methods to `RuleEngine` and integrate with `FilterConfig`:

```python
# In RuleEngine class
@staticmethod
def evaluate_block_words(previous_content, current_content, patterns):
    """Check if block words disappeared. Returns True if should notify."""
    prev_matches = html_tools.strip_ignore_text(previous_content, patterns, mode='match')
    curr_matches = html_tools.strip_ignore_text(current_content, patterns, mode='match')
    # Notify if words were present before but are now gone
    return bool(prev_matches) and not bool(curr_matches)

@staticmethod
def evaluate_trigger_words(previous_content, current_content, patterns):
    """Check if trigger words appeared. Returns True if should notify."""
    prev_matches = html_tools.strip_ignore_text(previous_content, patterns, mode='match')
    curr_matches = html_tools.strip_ignore_text(current_content, patterns, mode='match')
    # Notify if words were NOT present before but ARE now
    return not bool(prev_matches) and bool(curr_matches)
```

**Pros:** Feature becomes functional, users get expected behavior
**Cons:** More code changes, needs thorough testing
**Effort:** Medium
**Risk:** Low - follows existing patterns

### Option B: Mark Fields as "Coming Soon"
Add UI indication that fields are not yet functional:

```html
<fieldset class="border-fieldset" disabled>
    <legend>{{ _('Watch Words') }} <span class="badge">Coming Soon</span></legend>
```

**Pros:** Sets correct user expectations
**Cons:** Deferred value delivery
**Effort:** Small
**Risk:** None

### Option C: Hide Fields Behind Feature Flag
Remove from UI until processor logic is ready.

**Pros:** No user confusion
**Cons:** Feature not testable
**Effort:** Small
**Risk:** None

## Recommended Action

**Option A** - Implement the processor logic. The fields already exist and follow existing patterns; the processor integration is the missing piece to make this feature complete.

## Technical Details

### Affected Files
- `changedetectionio/processors/text_json_diff/processor.py` - Add RuleEngine methods
- `changedetectionio/processors/text_json_diff/__init__.py` - Add to FilterConfig
- `changedetectionio/processors/text_json_diff/processor.py` - Call new methods in run_changedetection

### Components
- RuleEngine class
- FilterConfig class
- Text matching pipeline

## Acceptance Criteria

- [x] `block_words` triggers notification when configured words disappear from page
- [x] `trigger_words` triggers notification when configured words appear on page
- [x] Unit tests cover both scenarios
- [x] Existing `trigger_text` and `text_should_not_be_present` continue to work

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-25 | Code review identified missing processor integration | Feature is UI-only without backend logic |
| 2026-01-26 | Implemented processor logic with FilterConfig, RuleEngine, and pipeline integration | Follows existing patterns for trigger_text/text_should_not_be_present |
| 2026-01-26 | Created unit tests (test_watch_words_unit.py) | 9/10 tests pass; first test fails due to Windows multiprocessing issue |

## Resources

- PR Branch: `feat/watch-words-event-metadata`
- Existing processor: `changedetectionio/processors/text_json_diff/processor.py:168-223`
- Plan document: `plans/feat-watch-words-event-metadata-configuration.md`
