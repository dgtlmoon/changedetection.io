#!/usr/bin/env python3
"""Bump the app version and refresh the translation catalogs in one step.

The release commit needs `__version__` and the .pot `Project-Id-Version` to agree
(extract_messages stamps the latter from the former). Doing them separately is easy
to half-forget, which then breaks the push *after* the release tag already exists.

Usage:
    python scripts/bump_version.py 0.60.3
"""

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT_FILE = REPO_ROOT / 'changedetectionio' / '__init__.py'
VERSION_RE = re.compile(r"""^(__version__ = )(['"])([^'"]*)\2""", re.M)

BABEL_STEPS = ['extract_messages', 'update_catalog', 'compile_catalog']


def run(*args):
    print(f"  $ {' '.join(args)}", flush=True)
    result = subprocess.run(args, cwd=REPO_ROOT)
    if result.returncode != 0:
        sys.exit(f"FAILED: {' '.join(args)}")


def main(argv):
    if len(argv) != 2:
        sys.exit(f"Usage: python {Path(__file__).name} <new-version>\n"
                 f"e.g.   python {Path(__file__).name} 0.60.3")

    new_version = argv[1].lstrip('v')
    if not re.fullmatch(r'\d+\.\d+\.\d+', new_version):
        sys.exit(f"Version must look like 0.60.3, got: {new_version!r}")

    source = INIT_FILE.read_text(encoding='utf-8')
    match = VERSION_RE.search(source)
    if not match:
        sys.exit(f"Could not find __version__ in {INIT_FILE.relative_to(REPO_ROOT)}")

    old_version = match.group(3)
    if old_version == new_version:
        sys.exit(f"Version is already {new_version}")

    print(f"Bumping {old_version} -> {new_version}", flush=True)
    INIT_FILE.write_text(VERSION_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{new_version}{m.group(2)}", source, count=1),
        encoding='utf-8')

    print("Refreshing translation catalogs:", flush=True)
    for step in BABEL_STEPS:
        run(sys.executable, 'setup.py', step)

    run(sys.executable, str(REPO_ROOT / 'scripts' / 'check_translations_version.py'))

    print(f"\nVersion {new_version} is in sync. Changed files:")
    subprocess.run(['git', 'status', '--short'], cwd=REPO_ROOT)
    print("\nNothing has been committed or tagged. To release, keep this chained --")
    print("a failed commit must not leave a tag pointing at the wrong revision:")
    print(f"  git add -u && git commit -m '{new_version}' && git tag {new_version} \\")
    print(f"    && git push origin master && git push origin {new_version}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
