# Translation Guide

## Updating Translations

To maintain consistency and minimize unnecessary changes in translation files, run these commands:

```bash
python setup.py extract_messages   # Extract translatable strings
python setup.py update_catalog     # Update all language files
python setup.py compile_catalog    # Compile to binary .mo files
```

## Configuration

All translation settings are configured in **`../../setup.cfg`** (single source of truth).

The configuration below is shown for reference - **edit `setup.cfg` to change settings**:

```ini
[extract_messages]
# Extract translatable strings from source code
mapping_file = babel.cfg
output_file = changedetectionio/translations/messages.pot
input_paths = changedetectionio
keywords = _ _l gettext
# Options to reduce unnecessary changes in .pot files
sort_by_file = true       # Keeps entries ordered by file path
width = 120               # Consistent line width (prevents rewrapping)
add_location = file       # Show file path only (not line numbers)

[update_catalog]
# Update existing .po files with new strings from .pot
# Note: 'locale' is omitted - Babel auto-discovers all catalogs in output_dir
input_file = changedetectionio/translations/messages.pot
output_dir = changedetectionio/translations
domain = messages
# Options for consistent formatting
width = 120               # Consistent line width
no_fuzzy_matching = true  # Avoids incorrect automatic matches

[compile_catalog]
# Compile .po files to .mo binary format
directory = changedetectionio/translations
domain = messages
```

**Key formatting options:**
- `sort_by_file = true` - Orders entries by file path (consistent ordering)
- `width = 120` - Fixed line width prevents text rewrapping
- `add_location = file` - Shows file path only, not line numbers (reduces git churn)
- `no_fuzzy_matching = true` - Prevents incorrect automatic fuzzy matches

## Why Use These Commands?

Running pybabel commands directly without consistent options causes:
- ❌ Entries get reordered differently each time
- ❌ Text gets rewrapped at different widths
- ❌ Line numbers change every edit (if not configured)
- ❌ Large diffs that make code review difficult

Using `python setup.py` commands ensures:
- ✅ Consistent ordering (by file path, not alphabetically)
- ✅ Consistent line width (120 characters, no rewrapping)
- ✅ File-only locations (no line number churn)
- ✅ No fuzzy matching (prevents incorrect auto-translations)
- ✅ Minimal diffs (only actual changes show up)
- ✅ Easier code review and git history

These commands read settings from `../../setup.cfg` automatically.

## Supported Languages

- `cs` - Czech (Čeština)
- `de` - German (Deutsch)
- `en_GB` - English (UK)
- `en_US` - English (US)
- `fr` - French (Français)
- `it` - Italian (Italiano)
- `ko` - Korean (한국어)
- `zh` - Chinese Simplified (中文简体)
- `zh_Hant_TW` - Chinese Traditional (繁體中文)

## Adding a New Language

1. Initialize the new language catalog:
   ```bash
   pybabel init -i changedetectionio/translations/messages.pot -d changedetectionio/translations -l NEW_LANG_CODE
   ```
2. Compile it:
   ```bash
   python setup.py compile_catalog
   ```

Babel will auto-discover the new language on subsequent translation updates.

## Translation Notes

From CLAUDE.md:
- Always use "monitor" or "watcher" terminology (not "clock")
- Use the most brief wording suitable
- When finding issues in one language, check ALL languages for the same issue
