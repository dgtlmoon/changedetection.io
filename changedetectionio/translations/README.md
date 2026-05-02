# Translators Guide

This document is for contributors who write templates (HTML) and for translators who maintain `.po` files.
It exists because fragmented `msgid`s — splitting a single sentence across multiple `_()` calls — cause
systematic translation breakage across many languages. Follow the patterns here to prevent that.

---

## Terminology

- **Always use "monitor" or "watcher"** for the concept of watching a URL — never the bare word "watch",
  which translates to "clock" (e.g. `hodinky` in Czech, `시계` in Korean, `時計` in Japanese).
- Use the **shortest suitable wording** for each language. If a language naturally uses the English
  derivative, prefer that.

---

## Template rules: do not fragment `msgid`s

### Why fragments break translation

The GNU gettext manual is explicit on this:

> **[Entire sentences](https://www.gnu.org/software/gettext/manual/html_node/Entire-sentences.html)**:
> Translatable strings should be entire sentences. Because gender/number declension depends on other
> parts of the sentence, half-sentence *"dumb string concatenation"* breaks in many languages other than English.

> **[No string concatenation](https://www.gnu.org/software/gettext/manual/html_node/No-string-concatenation.html)**:
> Placing adjacent `_()` calls is semantically equivalent to runtime `strcat` concatenation, so the same
> guideline applies. The manual also notes that "in some languages the translator might want to swap the
> order" of components.

> **[No embedded URLs](https://www.gnu.org/software/gettext/manual/html_node/No-embedded-URLs.html)**:
> URLs should not be written directly inside `msgid`s; they should be injected via `%(name)s` placeholders
> and values passed as kwargs.

> **[No unusual markup](https://www.gnu.org/software/gettext/manual/html_node/No-unusual-markup.html)**:
> "HTML markup, however, is common enough that it's probably ok to use in translatable strings."

Fragments break differently depending on language family:

| Language family | How fragmentation breaks it |
|---|---|
| SOV (Japanese, Korean, Turkish) | Verb-final word order can't be achieved when verb and subject are in separate fragments |
| Germanic (German) | Gender/case agreement between article and noun is lost across fragment boundaries |
| Romance (French, Spanish, Italian, Portuguese) | Adjective placement, subjunctive mood, verb agreement can't be maintained |
| Slavic (Czech, Ukrainian) | Case (driven by preposition/verb relationships) is easy to get wrong |
| CJK (Chinese, Japanese, Korean) | Modifier position and SVO-vs-topic-prominent differences can't be applied at fragment level |

A past workaround was redistributing translations across adjacent fragments and using `msgstr " "` (a
single space) to suppress unused fragments. This is fragile: as soon as the same short `msgid` is reused
in a different template, the redistributed translation is applied verbatim and breaks the new context.

---

## The four correct patterns

### Pattern 1 — Inline HTML embedding

Keep markup **inside** the `msgid`. Render with `| safe`. This also lets CJK translators decide how to
handle `<i>` (see CJK section below).

```jinja
{# BAD: three fragments; CJK translators can't see the <i> at all #}
{{ _('Helps reduce changes detected caused by sites shuffling lines around, combine with') }}
<i>{{ _('check unique lines') }}</i>
{{ _('below.') }}

{# GOOD: one msgid, rendered with |safe #}
{{ _('Helps reduce changes detected caused by sites shuffling lines around, combine with <i>check unique lines</i> below.') | safe }}
```

### Pattern 2 — URL as kwarg

Pass URLs via `%(name)s` so translators can freely reorder them.

```jinja
{# BAD: URL hardcoded between three fragments #}
{{ _('Use') }}
<a target="newwindow" href="https://github.com/caronc/apprise">{{ _('AppRise Notification URLs') }}</a>
{{ _('for notification to just about any service!') }}

{# GOOD: URL passed as kwarg, <a> embedded in the msgid #}
{{ _('Use <a target="newwindow" href="%(url)s">AppRise Notification URLs</a> for notification to just about any service!',
     url='https://github.com/caronc/apprise') | safe }}
```

### Pattern 3 — Literal `{{}}` escape as kwarg

Jinja2 would double-interpolate `{{token}}` inside a `_()` call. Pass it as a kwarg instead.

```jinja
{# BAD: literal {{token}} in the middle forces splitting #}
{{ _('Accepts the') }} <code>{{ '{{token}}' }}</code> {{ _('placeholders listed below') }}

{# GOOD: literal passed as kwarg; msgid stays as an entire sentence #}
{{ _('Accepts the <code>%(token)s</code> placeholders listed below', token='{{token}}') | safe }}
```

### Pattern 4 — `{% if %}` outside the `msgid`

Move conditional branches outside `_()` so each branch is a complete sentence, not a fragment.

```jinja
{# BAD: three fragments; SOV languages can't reorder %(title)s relative to "URL or Title" #}
{{ _('URL or Title') }}{% if active_tag_uuid %} {{ _('in') }} '{{ active_tag.title }}'{% endif %}

{# GOOD: branch between two complete msgids; each language can freely reorder %(title)s #}
{% if active_tag_uuid %}
  {{ _("URL or Title in '%(title)s'", title=active_tag.title) }}
{% else %}
  {{ _('URL or Title') }}
{% endif %}
```

---

## CJK italic policy

CJK fonts typically have no true italic cut — `<i>` falls back to a mechanical slant that reduces
legibility. Now that `<i>` is inside `msgid`s, CJK translators can handle it per-locale. Apply this policy
for `ja` / `zh` / `zh_Hant_TW`:

| Context | Action |
|---|---|
| `<i>` used for general emphasis | Replace with `<strong>`, or drop if the emphasis is self-evident |
| `<strong><i>...</i></strong>` | Collapse to `<strong>...</strong>` |
| `<i>` wrapping a UI term (e.g. "check unique lines") | Wrap in locale-conventional quotation marks: 「」 for `ja`/`zh_Hant_TW`, `""` for `zh` |

---

## Translation workflow

**Always use these commands** — they read consistent settings from `setup.cfg` and produce minimal diffs:

```bash
python setup.py extract_messages   # Extract translatable strings from source
python setup.py update_catalog     # Propagate new msgids to all .po files
python setup.py compile_catalog    # Compile .po files to binary .mo files
```

Running `pybabel` directly without the project options causes reordering, rewrapping, and line-number
churn that makes diffs hard to review.

### Configuration

All translation settings are in `setup.cfg` (single source of truth):

```ini
[extract_messages]
mapping_file = babel.cfg
output_file = changedetectionio/translations/messages.pot
input_paths = changedetectionio
keywords = _ _l gettext
sort_by_file = true       # Keeps entries ordered by file path
width = 120               # Consistent line width (prevents rewrapping)
add_location = file       # Show file path only (not line numbers)

[update_catalog]
input_file = changedetectionio/translations/messages.pot
output_dir = changedetectionio/translations
domain = messages
width = 120
no_fuzzy_matching = true  # Avoids incorrect automatic matches

[compile_catalog]
directory = changedetectionio/translations
domain = messages
```

---

## Multi-language fix process

When you find a translation error in **any** language, you must check all others for the same `msgid`:

```bash
for lang in cs de en_GB en_US es fr it ja ko pt_BR tr uk zh zh_Hant_TW; do
  echo "=== $lang ===" && grep -A1 'msgid "YourString"' changedetectionio/translations/$lang/LC_MESSAGES/messages.po
done
```

1. Identify every language with the same problem
2. Fix all affected `.po` files in the same session
3. Recompile: `python setup.py compile_catalog`

Never fix one language and move on.

---

## Supported languages

| Code | Language |
|---|---|
| `cs` | Czech (Čeština) |
| `de` | German (Deutsch) |
| `en_GB` | English (UK) |
| `en_US` | English (US) |
| `es` | Spanish (Español) |
| `fr` | French (Français) |
| `it` | Italian (Italiano) |
| `ja` | Japanese (日本語) |
| `ko` | Korean (한국어) |
| `pt_BR` | Portuguese (Brasil) |
| `tr` | Turkish (Türkçe) |
| `uk` | Ukrainian (Українська) |
| `zh` | Chinese Simplified (中文简体) |
| `zh_Hant_TW` | Chinese Traditional (繁體中文) |

## Adding a new language

```bash
pybabel init -i changedetectionio/translations/messages.pot \
             -d changedetectionio/translations \
             -l NEW_LANG_CODE
# Reset POT-Creation-Date to the sentinel so it matches the other catalogs
sed -i 's|^"POT-Creation-Date: .*\\n"$|"POT-Creation-Date: 1970-01-01 00:00+0000\\n"|' \
  changedetectionio/translations/NEW_LANG_CODE/LC_MESSAGES/messages.po
python setup.py compile_catalog
```

Babel auto-discovers the new language on subsequent runs.

---

## Dennis linter

We use [mozilla/dennis](https://github.com/mozilla/dennis) to enforce technical correctness in `.po` and `.pot` files.
See the [Table of Warnings and Errors](https://dennis.readthedocs.io/en/latest/linting.html#table-of-warnings-and-errors)
for the full list of rules.

### Running the linter locally

To match the CI checks, run the following commands:

```bash
# Check for errors only (always enforced)
dennis-cmd lint --errorsonly changedetectionio/translations/

# Check for warnings (excluding W302 unchanged translations)
dennis-cmd lint --excluderules=W302 changedetectionio/translations/
```

### Common problems and resolutions

#### HTML tag mismatch (`W303`)

The `W303` rule ensures that HTML tags in the `msgstr` match the `msgid`. This is crucial for catching broken markup (e.g., missing closing tags).

##### Handling intentional deviations and false positives

Some W303 warnings are intentional or result from upstream false positives.
Use the `dennis-ignore: W303` comment in the source files (templates or Python code) within a `TRANSLATORS` comment to suppress these warnings.
This ensures the ignore instruction is extracted into the `.po` files.

- **CJK italic policy**: When replacing `<i>` with locale-conventional quotation marks, tags will no longer match.
- **Upstream false positive**: Dennis misinterprets certain HTML tags (e.g., `<title>`) within `msgstr`. See https://github.com/mozilla/dennis/issues/213.

**Examples in Jinja2 templates:**

```jinja
{# TRANSLATORS: CJK fonts lack native italics; allow substitution with conventional local styling. dennis-ignore: W303 #}
<p>{{ _('These settings are <strong><i>added</i></strong> to any existing watch configurations.')|safe }}</p>

{# TRANSLATORS: dennis-ignore: W303 - False positive caused by <title>. https://github.com/mozilla/dennis/issues/213 #}
<td>{{ _('The page title of the watch, uses <title> if not set, falls back to URL') }}</td>
```

**Example in Python source:**

```python
# dennis-ignore: W303 - False positive caused by <title>. https://github.com/mozilla/dennis/issues/213
use_page_title_in_list = BooleanField(_l('Use page <title> in watch overview list'))
```

---

## CI linter

A GitHub Actions job (`lint-template-i18n`) checks for adjacent `{{ _(...) }}` calls on the same line
separated only by HTML — the primary symptom of fragmented `msgid`s. It enforces a declining baseline:
the count of existing violations may only go down, never up. When you fix a template, lower the
`BASELINE_LIMIT` in `.github/workflows/test-only.yml` by the number of lines you fixed.

See [issue #4074](https://github.com/dgtlmoon/changedetection.io/issues/4074) for full background and
[PR #4076](https://github.com/dgtlmoon/changedetection.io/pull/4076) for worked consolidation examples.
