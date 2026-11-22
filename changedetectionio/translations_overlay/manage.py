#!/usr/bin/env python3
"""Manage the deployment wording overlay catalogs.

The overlay is a second gettext tree merged on top of ``changedetectionio/translations`` at
runtime (see the BABEL_TRANSLATION_DIRECTORIES block in ``changedetectionio/flask_app.py``).
Flask-Babel merges the two catalogs per-locale, later directory winning per-message, so an
overlay catalog only needs the msgids whose wording this deployment changes.

The catch this tooling exists to manage: an override is keyed on the exact upstream msgid.
When upstream edits a string - even a typo fix - the override stops matching and that string
silently reverts to upstream wording. ``check`` turns that silent revert into a hard failure.

    python changedetectionio/translations_overlay/manage.py check
    python changedetectionio/translations_overlay/manage.py compile
    python changedetectionio/translations_overlay/manage.py add de
"""

import argparse
import os
import sys

from babel.messages.mofile import read_mo, write_mo
from babel.messages.pofile import read_po, write_po

OVERLAY_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.join(os.path.dirname(OVERLAY_DIR), 'translations')
POT_FILE = os.path.join(BASE_DIR, 'messages.pot')


def _po_path(root, locale):
    return os.path.join(root, locale, 'LC_MESSAGES', 'messages.po')


def _mo_path(root, locale):
    return os.path.join(root, locale, 'LC_MESSAGES', 'messages.mo')


def overlay_locales():
    """Locales that have an overlay catalog, sorted."""
    return sorted(d for d in os.listdir(OVERLAY_DIR) if os.path.isfile(_po_path(OVERLAY_DIR, d)))


def _load(path):
    with open(path, 'rb') as fp:
        return read_po(fp)


def _message_ids(catalog):
    """Real (non-header, non-obsolete) message ids in a catalog."""
    return {m.id for m in catalog if m.id}


def cmd_check(_args):
    """Validate every overlay catalog against the base catalogs. Returns an exit code."""
    if not os.path.isfile(POT_FILE):
        print(
            f"error: {POT_FILE} missing - run `python setup.py extract_messages` first",
            file=sys.stderr,
        )
        return 1

    known_ids = _message_ids(_load(POT_FILE))
    problems = []

    for locale in overlay_locales():
        overlay = _load(_po_path(OVERLAY_DIR, locale))

        # 1. Every overridden msgid must still exist upstream, or the override is dead weight.
        for message in overlay:
            if message.id and message.id not in known_ids:
                problems.append(
                    f"{locale}: msgid no longer exists in messages.pot, override is dead:\n"
                    f"         {message.id!r}"
                )

        # 2. An override with an empty msgstr is dropped by the compiler, so it does nothing
        #    while looking like it does something.
        for message in overlay:
            if message.id and not message.string:
                problems.append(
                    f"{locale}: empty msgstr, override will be a no-op:\n         {message.id!r}"
                )

        base_po = _po_path(BASE_DIR, locale)
        if not os.path.isfile(base_po):
            problems.append(f"{locale}: no base catalog at {base_po} - is this a real locale?")
        else:
            # 3. Flask-Babel copies `plural` from the last catalog that has one, so a wrong
            #    Plural-Forms header here breaks plurals for every string in the language,
            #    not just the overridden ones.
            base_plural = _load(base_po).plural_expr
            if overlay.plural_expr != base_plural:
                problems.append(
                    f"{locale}: Plural-Forms disagrees with the base catalog and would override it\n"
                    f"         overlay: {overlay.plural_expr}\n"
                    f"         base:    {base_plural}"
                )

        # 4. The .mo is what actually gets loaded; a stale one means edits to the .po do nothing.
        mo_file = _mo_path(OVERLAY_DIR, locale)
        expected = {m.id for m in overlay if m.id and m.string}
        if not expected:
            if os.path.isfile(mo_file) and _message_ids(_read_mo(mo_file)):
                problems.append(
                    f"{locale}: .po has no overrides but .mo still contains some - recompile"
                )
        elif not os.path.isfile(mo_file):
            problems.append(
                f"{locale}: {os.path.basename(mo_file)} missing - run `manage.py compile`"
            )
        elif _message_ids(_read_mo(mo_file)) != expected:
            problems.append(f"{locale}: .mo is out of date with .po - run `manage.py compile`")

    if problems:
        print(f"{len(problems)} problem(s) in the translation overlay:\n", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    total = sum(
        len({m.id for m in _load(_po_path(OVERLAY_DIR, loc)) if m.id}) for loc in overlay_locales()
    )
    print(
        f"overlay ok: {total} override(s) across {len(overlay_locales())} locale(s): {', '.join(overlay_locales()) or '-'}"
    )
    return 0


def _read_mo(path):
    with open(path, 'rb') as fp:
        return read_mo(fp)


def cmd_compile(_args):
    for locale in overlay_locales():
        catalog = _load(_po_path(OVERLAY_DIR, locale))
        mo_file = _mo_path(OVERLAY_DIR, locale)
        with open(mo_file, 'wb') as fp:
            write_mo(fp, catalog)
        overrides = len({m.id for m in catalog if m.id and m.string})
        print(
            f"compiled {locale}: {overrides} override(s) -> {os.path.relpath(mo_file, os.getcwd())}"
        )
    return 0


def cmd_add(args):
    """Bootstrap an empty overlay catalog for a locale, inheriting the base catalog's headers."""
    locale = args.locale
    base_po = _po_path(BASE_DIR, locale)
    if not os.path.isfile(base_po):
        print(f"error: no base catalog for {locale!r} at {base_po}", file=sys.stderr)
        return 1

    target = _po_path(OVERLAY_DIR, locale)
    if os.path.exists(target):
        print(f"error: {target} already exists", file=sys.stderr)
        return 1

    base = _load(base_po)
    # Take the language metadata (crucially Plural-Forms) from base, but none of the messages.
    catalog = type(base)(
        locale=base.locale,
        domain='messages',
        project=base.project,
        msgid_bugs_address=base.msgid_bugs_address,
        header_comment=(
            f'# Deployment wording overlay for changedetection.io - {locale}\n'
            '# Merged on top of the base catalog for this language; only list the msgids\n'
            '# whose wording this deployment changes. See ../../README.md.\n'
        ),
    )
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, 'wb') as fp:
        write_po(fp, catalog, width=120)
    print(f"created {os.path.relpath(target, os.getcwd())}")
    print("add your msgid/msgstr pairs, then run `manage.py compile`")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser(
        'check', help='validate overlay catalogs against the base catalogs'
    ).set_defaults(fn=cmd_check)
    sub.add_parser('compile', help='compile overlay .po files to .mo').set_defaults(fn=cmd_compile)
    add = sub.add_parser('add', help='create an overlay catalog for a locale')
    add.add_argument('locale')
    add.set_defaults(fn=cmd_add)
    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == '__main__':
    main()
