# Translation overlay

An optional second catalog layer that lets a deployment reword individual strings **without forking
any template or Python source**.

It exists because rewording a string normally means editing the `_()` call at its call site, and that
edit conflicts on every upstream merge, forever. The overlay moves the reworded text out of the
source tree and into a catalog keyed on the upstream `msgid`, so the call site keeps upstream's
string verbatim and carries no diff at all.

Typical uses: white-labelling, or suppressing instructions that don't apply to how you run the app —
e.g. telling users to set `WEBDRIVER_URL` when the operator, not the user, controls that.

## How it works

`BABEL_TRANSLATION_DIRECTORIES` is a `;` separated list. For each locale, Flask-Babel loads one
catalog per directory and merges them in order (`Domain.get_translations` → babel
`Translations.merge` → `dict.update`), so a **later directory overrides an earlier one per message**,
not per file.

```
changedetectionio/translations/          <- base, upstream
changedetectionio/translations_overlay/  <- this layer, merged on top
```

So for German, `translations/de` and `translations_overlay/de` become a single catalog: the msgids
listed in the overlay take the overlay's text, and the other ~580 keep their upstream German. A
language with no overlay catalog is completely unaffected, as is a msgid the overlay doesn't mention.

Overriding **English** works too. The `en_GB` base catalog has every `msgstr` empty, so English
currently renders straight from the msgids; an overlay `en_GB` entry fills that gap.

Wiring is in `changedetectionio/flask_app.py`. The directory is picked up only if it exists, and
`TRANSLATION_OVERLAY_DIR` can point somewhere else (e.g. a path mounted into a container). No
directory, or a directory with no overrides, means no behaviour change.

## The failure mode this needs guarding

An override matches on the **exact upstream msgid**. When upstream edits that string — even fixing a
typo — the override stops matching and the string silently reverts to upstream wording. It fails
soft, so nothing tells you.

`manage.py check` turns that into a hard failure, and `tests/test_translation_overlay.py` runs it in
CI. It also catches three other quiet ways an override does nothing:

| Problem | Why it bites |
|---|---|
| msgid no longer in `messages.pot` | upstream reworded it; your override is dead |
| empty `msgstr` | the compiler drops empty entries, so it silently does nothing |
| `Plural-Forms` differs from base | Flask-Babel copies `plural` from the last catalog that has one, so a wrong header here breaks plurals for **every** string in that language |
| `.mo` stale or missing | the `.mo` is what's loaded; `.po` edits alone have no effect |

## Workflow

```bash
# create a catalog for a language (inherits Plural-Forms from the base catalog)
python changedetectionio/translations_overlay/manage.py add de

# ... add msgid/msgstr pairs, copying the msgid verbatim from translations/messages.pot ...

python changedetectionio/translations_overlay/manage.py compile   # .po -> .mo
python changedetectionio/translations_overlay/manage.py check     # validate (also runs in CI)
```

Both `.po` and `.mo` are committed, matching how the base catalogs are handled.

Overriding a string in English only is fine — other languages keep their upstream translation of the
original wording. If the reworded English changes the *meaning* rather than the phrasing, add the
matching override per language, otherwise the translations will drift from what English now says.

Writing the override text itself follows the same rules as any other catalog entry: see
[`../translations/README.md`](../translations/README.md), especially "do not fragment msgids".
