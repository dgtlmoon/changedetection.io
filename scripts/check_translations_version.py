#!/usr/bin/env python3
"""Check that the version in messages.pot matches the app version.

`python setup.py extract_messages` stamps `Project-Id-Version` in the .pot
header from `changedetectionio.__version__`, so a mismatch means the version
was bumped without re-extracting the translation catalogs.

Run manually, or via the pre-push hook in .pre-commit-config.yaml.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = REPO_ROOT / 'changedetectionio' / '__init__.py'
POT_FILE = REPO_ROOT / 'changedetectionio' / 'translations' / 'messages.pot'


def get_app_version():
    match = re.search(r"""^__version__ = ['"]([^'"]*)['"]""",
                      INIT_FILE.read_text(encoding='utf-8'), re.M)
    return match.group(1) if match else None


def get_pot_version():
    # "Project-Id-Version: changedetection.io 0.60.2\n"
    match = re.search(r'^"Project-Id-Version: changedetection\.io ([^\\"]+)',
                      POT_FILE.read_text(encoding='utf-8'), re.M)
    return match.group(1).strip() if match else None


def main():
    app_version = get_app_version()
    pot_version = get_pot_version()

    if not app_version:
        print(f"Could not find __version__ in {INIT_FILE.relative_to(REPO_ROOT)}")
        return 1

    if not pot_version:
        print(f"Could not find 'Project-Id-Version: changedetection.io <version>' "
              f"in {POT_FILE.relative_to(REPO_ROOT)}")
        return 1

    if app_version != pot_version:
        print(f"Translation catalog version mismatch:")
        print(f"  app  ({INIT_FILE.relative_to(REPO_ROOT)}): {app_version}")
        print(f"  .pot ({POT_FILE.relative_to(REPO_ROOT)}): {pot_version}")
        print()
        print("Refresh the catalogs and commit the result:")
        print("  python setup.py extract_messages")
        print("  python setup.py update_catalog")
        print("  python setup.py compile_catalog")
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
