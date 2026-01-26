---
status: resolved
priority: p2
issue_id: "002"
tags: [code-review, css, maintainability]
dependencies: []
---

# Move Inline CSS to Stylesheet in diff.html

## Problem Statement

The new watch info header in `diff.html` uses 15 inline `style` attributes instead of CSS classes. This violates separation of concerns, makes theming difficult, and is inconsistent with the rest of the codebase which uses external stylesheets.

## Findings

### Evidence from Code Review
Location: `changedetectionio/blueprint/ui/templates/diff.html` (lines 96-125)

```html
<div class="watch-info-header" style="background: var(--color-background-tab, #f5f5f5); padding: 12px 15px; margin-bottom: 15px; border-radius: 5px; border-left: 4px solid var(--color-accent, #5c6bc0);">
    <div class="event-details" style="margin-bottom: 10px;">
        <strong style="font-size: 1.1em;">...</strong>
        <span style="margin-left: 15px;">...</span>
    </div>
    <div class="watch-words-display" style="display: flex; gap: 30px; flex-wrap: wrap;">
        <div class="block-words" style="flex: 1; min-width: 200px;">
            <strong style="color: #d32f2f;">...</strong>
            <span style="font-family: monospace; background: rgba(211, 47, 47, 0.1); padding: 2px 6px; border-radius: 3px; margin-left: 5px;">
```

### Issues
1. **Hardcoded colors** (`#d32f2f`, `#388e3c`) - won't adapt to dark mode
2. **Repeated styles** - same patterns used multiple times
3. **Unmaintainable** - can't be overridden via CSS
4. **Inconsistent** - rest of codebase uses `diff.css` for diff page styles

## Proposed Solutions

### Option A: Extract to diff.css (Recommended)

Add new CSS rules to `changedetectionio/static/styles/diff.css`:

```css
.watch-info-header {
  background: var(--color-background-tab, #f5f5f5);
  padding: 12px 15px;
  margin-bottom: 15px;
  border-radius: 5px;
  border-left: 4px solid var(--color-accent, #5c6bc0);
}

.watch-info-header .event-details {
  margin-bottom: 10px;
}

.watch-info-header .event-label {
  font-size: 1.1em;
}

.watch-info-header .event-value {
  margin-left: 15px;
}

.watch-info-header .watch-words-display {
  display: flex;
  gap: 30px;
  flex-wrap: wrap;
}

.watch-info-header .block-words,
.watch-info-header .trigger-words {
  flex: 1;
  min-width: 200px;
}

.watch-info-header .block-words strong {
  color: var(--color-error, #d32f2f);
}

.watch-info-header .trigger-words strong {
  color: var(--color-success, #388e3c);
}

.watch-info-header .word-list {
  font-family: monospace;
  background: var(--color-tag-bg, rgba(0, 0, 0, 0.1));
  padding: 2px 6px;
  border-radius: 3px;
  margin-left: 5px;
}
```

Then update the template to use classes:

```html
<div class="watch-info-header">
    <div class="event-details">
        <strong class="event-label">{{ _('Event Details') }}:</strong>
        <span class="event-value">...</span>
    </div>
    <div class="watch-words-display">
        <div class="block-words">
            <strong>{{ _('Notify when DISAPPEARS') }}:</strong>
            <span class="word-list">{{ watch_a.get('block_words') | join(', ') }}</span>
        </div>
    </div>
</div>
```

**Pros:** Follows codebase conventions, supports theming, maintainable
**Cons:** More files touched
**Effort:** Small
**Risk:** Low

## Recommended Action

**Option A** - Extract inline styles to `diff.css`. This follows existing patterns and enables proper theming support.

## Technical Details

### Affected Files
- `changedetectionio/static/styles/diff.css` - Add new CSS rules
- `changedetectionio/blueprint/ui/templates/diff.html` - Remove inline styles, add classes

## Acceptance Criteria

- [x] No inline `style` attributes in the watch-info-header section
- [x] All styling moved to diff.css with proper CSS classes
- [x] Colors use CSS custom properties for theme support
- [x] Visual appearance unchanged

## Work Log

| Date | Action | Learnings |
|------|--------|-----------|
| 2026-01-25 | Code review identified inline CSS anti-pattern | 15 inline styles should use external stylesheet |
| 2026-01-26 | Moved inline CSS to diff.css | Added .watch-info-header and related classes with CSS custom properties |

## Resources

- PR Branch: `feat/watch-words-event-metadata`
- Existing stylesheet: `changedetectionio/static/styles/diff.css`
