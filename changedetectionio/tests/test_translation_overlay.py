"""Guards for the translation overlay layer (changedetectionio/translations_overlay).

The overlay is a second gettext tree merged on top of ``changedetectionio/translations``, letting a
deployment reword individual strings without editing the ``_()`` call site. See that directory's
README.md. Three separate things can break it, so there is a test for each.

1. Overlay entries key on the exact upstream msgid. When a string is reworded upstream the override
   stops matching and silently reverts to upstream wording - no error, no log entry.
   ``test_overlay_catalogs_are_valid`` makes that a build failure.

2. The layering relies on Flask-Babel merging catalogs with ``dict.update`` semantics (later
   directory wins per-message). Were a Flask-Babel upgrade to change that to an ``add_fallback``
   chain, overrides would stop applying while everything still looked fine.
   ``test_overlay_overrides_a_string_in_a_rendered_page`` pins it against a real rendered page.

3. The directory has to actually reach ``BABEL_TRANSLATION_DIRECTORIES``.
   ``test_overlay_dir_*`` cover the wiring in flask_app.py, including the env var.
"""

import os
import subprocess
import sys

import pytest
from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from flask import url_for

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(PKG_DIR)
OVERLAY_DIR = os.path.join(PKG_DIR, 'translations_overlay')
BASE_DIR = os.path.join(PKG_DIR, 'translations')
MANAGE = os.path.join(OVERLAY_DIR, 'manage.py')

# A msgid that renders as a settings-page tab label. The test asserts it is present *before*
# overriding it, so a rename upstream fails loudly rather than making the test silently vacuous.
OVERRIDDEN_MSGID = 'Global Filters'
SENTINEL = 'zzOverlaySentinelFiltersZZ'

# A helper text on the Restock & Price Detection (restock_diff) per-watch settings tab.
# Wired through gettext so the overlay can reword it (see ``test_overlay_overrides_a_string_in_a_rendered_page``).
RESTOCK_MSGID = 'Changes in price should trigger a notification'
RESTOCK_SENTINEL = 'zzOverlaySentinelRestockZZ'


def _write_mo(root, locale, entries):
    """Write a compiled catalog at <root>/<locale>/LC_MESSAGES/messages.mo."""
    catalog = Catalog(locale=locale, domain='messages')
    for msgid, msgstr in entries.items():
        catalog.add(msgid, msgstr)
    mo_dir = os.path.join(root, locale, 'LC_MESSAGES')
    os.makedirs(mo_dir, exist_ok=True)
    with open(os.path.join(mo_dir, 'messages.mo'), 'wb') as fp:
        write_mo(fp, catalog)


def _import_app_with(env_overlay_dir):
    """Import flask_app in a clean subprocess and report its BABEL_TRANSLATION_DIRECTORIES.

    Has to be a subprocess: the config is built at module import time, so it cannot be re-evaluated
    under a different environment once flask_app is already in sys.modules.
    """
    env = dict(os.environ, TRANSLATION_OVERLAY_DIR=env_overlay_dir)
    result = subprocess.run(
        [
            sys.executable,
            '-c',
            'from changedetectionio import flask_app;'
            'print("DIRS=" + flask_app.app.config["BABEL_TRANSLATION_DIRECTORIES"])',
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
    )
    assert result.returncode == 0, f"importing flask_app failed:\n{result.stdout}\n{result.stderr}"
    line = [l for l in result.stdout.splitlines() if l.startswith('DIRS=')]
    assert line, f"no config line in output:\n{result.stdout}\n{result.stderr}"
    return line[0][len('DIRS=') :].split(';')


# ---------------------------------------------------------------------------
# 1. The overlay catalogs shipped in this repo are internally consistent
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not os.path.isdir(OVERLAY_DIR), reason='no translation overlay in this deployment'
)
def test_overlay_catalogs_are_valid():
    """Every override must still match an upstream msgid, be non-empty, and be compiled.

    A failure here usually means upstream edited a string the overlay overrides. Re-copy the new
    msgid verbatim from translations/messages.pot into the overlay catalog, then recompile with
    `python changedetectionio/translations_overlay/manage.py compile`.
    """
    result = subprocess.run([sys.executable, MANAGE, 'check'], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"translation overlay is invalid:\n{result.stdout}{result.stderr}"
    )


@pytest.mark.skipif(
    not os.path.isdir(OVERLAY_DIR), reason='no translation overlay in this deployment'
)
def test_overlay_locales_have_a_base_catalog():
    """An overlay for a locale the app does not ship never loads, so it is silently dead."""
    for locale in sorted(os.listdir(OVERLAY_DIR)):
        if not os.path.isfile(os.path.join(OVERLAY_DIR, locale, 'LC_MESSAGES', 'messages.po')):
            continue
        assert os.path.isdir(os.path.join(BASE_DIR, locale)), (
            f"overlay locale {locale!r} has no base catalog in translations/"
        )


# ---------------------------------------------------------------------------
# 2. The merge actually happens, end to end, on a real page
# ---------------------------------------------------------------------------


def test_overlay_overrides_a_string_in_a_rendered_page(client, live_server, tmp_path):
    """A real overlay catalog changes real rendered output, and only the string it names."""
    app = client.application

    # The rest of this test injects its own directory, which would still pass if flask_app.py had
    # stopped configuring the real one. Tie the two together so that regression fails here too.
    if os.path.isdir(OVERLAY_DIR):
        configured = app.config['BABEL_TRANSLATION_DIRECTORIES'].split(';')
        assert OVERLAY_DIR in configured, (
            f"{OVERLAY_DIR} exists but is not in BABEL_TRANSLATION_DIRECTORIES ({configured})"
        )

    baseline = client.get(url_for('settings.settings_page'))
    assert baseline.status_code == 200
    assert OVERRIDDEN_MSGID.encode() in baseline.data, (
        f"{OVERRIDDEN_MSGID!r} no longer renders on the settings page - this test needs a new msgid"
    )
    assert SENTINEL.encode() not in baseline.data

    overlay = tmp_path / 'overlay'
    # en_GB is BABEL_DEFAULT_LOCALE, and the test client sends no Accept-Language header
    _write_mo(str(overlay), 'en_GB', {OVERRIDDEN_MSGID: SENTINEL})

    # The default Domain delegates to the app-level directory list, and caches per (locale, domain),
    # so both have to be touched for a new catalog to be picked up mid-process.
    dirs = app.extensions['babel'].translation_directories
    domain_cache = app.extensions['babel'].instance.domain_instance.cache
    dirs.append(str(overlay))
    domain_cache.clear()
    try:
        overridden = client.get(url_for('settings.settings_page'))
        assert overridden.status_code == 200
        assert SENTINEL.encode() in overridden.data, (
            'overlay catalog did not override the base catalog'
        )
        assert OVERRIDDEN_MSGID.encode() not in overridden.data, 'base wording is still rendering'
        # Neighbouring tab label, deliberately not in the overlay - merging must not drop it
        assert b'UI Options' in overridden.data, (
            'overlay replaced the catalog instead of merging into it'
        )
    finally:
        dirs.remove(str(overlay))
        domain_cache.clear()

    restored = client.get(url_for('settings.settings_page'))
    assert SENTINEL.encode() not in restored.data
    assert OVERRIDDEN_MSGID.encode() in restored.data, 'base wording did not come back'


def test_restock_diff_helper_texts_route_through_gettext(client, tmp_path):
    """The Restock & Price Detection helper texts are translated through gettext (issue #4378).

    These strings are rendered by ``processor_settings_form.extra_form_content()`` through a bare
    Jinja2 environment, so the guard is the same one pinning the overlay merge: override an msgid
    in a real translated locale and assert it replaces the wording on the rendered edit page.
    """
    app = client.application

    test_url = url_for('test_endpoint', _external=True)
    client.post(
        url_for("ui.ui_views.form_quick_watch_add"),
        data={"url": test_url, "tags": '', 'processor': 'restock_diff', 'fetch_backend': 'html_requests'},
        follow_redirects=True
    )
    datastore = app.config.get('DATASTORE')
    uuid = next(iter(datastore.data['watching']))
    edit_url = url_for('ui.ui_edit.edit_page', uuid=uuid)

    baseline = client.get(edit_url)
    assert baseline.status_code == 200
    assert RESTOCK_MSGID.encode() in baseline.data, (
        f"{RESTOCK_MSGID!r} no longer renders on the edit page - this test needs a new msgid"
    )
    assert RESTOCK_SENTINEL.encode() not in baseline.data

    overlay = tmp_path / 'overlay'
    _write_mo(str(overlay), 'en_GB', {RESTOCK_MSGID: RESTOCK_SENTINEL})

    dirs = app.extensions['babel'].translation_directories
    domain_cache = app.extensions['babel'].instance.domain_instance.cache
    dirs.append(str(overlay))
    domain_cache.clear()
    try:
        overridden = client.get(edit_url)
        assert overridden.status_code == 200
        assert RESTOCK_SENTINEL.encode() in overridden.data, (
            'restock_diff helper text did not route through gettext'
        )
        assert RESTOCK_MSGID.encode() not in overridden.data, 'upstream wording is still rendering'
        assert b'Maximum amount, Trigger a change/notification when the price rises' in overridden.data, (
            'overlay replaced the catalog instead of merging into it'
        )
    finally:
        dirs.remove(str(overlay))
        domain_cache.clear()


# ---------------------------------------------------------------------------
# 3. flask_app.py wires the directory up, and stays a no-op when there isn't one
# ---------------------------------------------------------------------------


def test_overlay_dir_from_env_var_is_used(tmp_path):
    overlay = tmp_path / 'my-overlay'
    overlay.mkdir()
    dirs = _import_app_with(str(overlay))
    assert dirs[-1] == str(overlay), f"TRANSLATION_OVERLAY_DIR not appended, got {dirs}"
    assert dirs[0] == BASE_DIR, 'base catalog must stay first so the overlay wins on conflicts'


def test_missing_overlay_dir_is_a_noop(tmp_path):
    """No overlay directory means the config is exactly what it was before the feature existed."""
    dirs = _import_app_with(str(tmp_path / 'does-not-exist'))
    assert dirs == [BASE_DIR], f"expected only the base catalog, got {dirs}"
