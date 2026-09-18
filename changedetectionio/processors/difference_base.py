"""
Base contract + shared helpers for a processor's history/diff ("difference") page.

Each processor can provide a custom history/diff view by shipping a
``processors/<name>/difference.py`` module that exposes a module-level ``render(...)``
function. The route ``blueprint/ui/diff.py::diff_history_page`` resolves it via
``get_processor_submodule(processor_name, 'difference')`` and calls ``render(...)`` with the
keyword contract below; processors without one fall back to ``text_json_diff``.

This module formalises that previously-implicit contract:
  * ``DifferenceRenderer`` documents the ``render(...)`` signature (for typing/static checks).
  * ``resolve_diff_versions()`` centralises the from/to version selection that was duplicated
    between ``text_json_diff/difference.py`` and the ``/diff/.../llm-summary`` route, so every
    processor resolves "which two snapshots am I comparing" identically.
"""
from dataclasses import dataclass
from typing import Any, List, Protocol, runtime_checkable

from loguru import logger


@runtime_checkable
class DifferenceRenderer(Protocol):
    """The contract a processor's ``difference.py`` module must satisfy.

    Implemented as a module-level function (not a class method), so a conforming module looks
    like::

        def render(watch, datastore, request, url_for, render_template, flash, redirect,
                   extract_form=None):
            ...
            return render_template(...)   # a Flask response

    Returns a Flask response (rendered template / redirect / make_response).
    """

    def render(self, watch, datastore, request, url_for, render_template, flash, redirect,
               extract_form: Any = None) -> Any:
        ...


@dataclass
class DiffVersions:
    """The resolved comparison window for a difference page."""
    dates: List[str]          # all history timestamps (string keys), oldest -> newest
    from_version: str         # older snapshot timestamp being compared
    to_version: str           # newer snapshot timestamp being compared
    from_contents: str        # raw snapshot text for from_version
    to_contents: str          # raw snapshot text for to_version
    viewing_latest: bool      # True when to_version is the newest snapshot
    note: str                 # human note when not viewing the latest changes ('' otherwise)


def resolve_diff_versions(watch, request) -> DiffVersions:
    """Resolve which two snapshots a difference page should compare.

    Default ``from_version`` is the snapshot closest to the user's last view (so the page opens
    on "what changed since I last looked"), falling back to the second-newest snapshot. Default
    ``to_version`` is the newest snapshot. Both are overridable via ``?from_version=`` /
    ``?to_version=`` query args. The caller is responsible for guaranteeing at least two
    snapshots exist (the route already redirects otherwise).

    Note: read the versions BEFORE calling ``datastore.set_last_viewed()`` — the default
    ``from_version`` depends on the pre-update last-viewed timestamp.
    """
    dates = list(watch.history.keys())

    best_last_viewed = watch.get_from_version_based_on_last_viewed
    from_default = best_last_viewed if best_last_viewed else dates[-2]
    from_version = request.args.get('from_version', from_default)
    to_version = request.args.get('to_version', dates[-1])

    try:
        to_contents = watch.get_history_snapshot(timestamp=to_version)
    except Exception as e:
        logger.error(f"Unable to read watch history to-version for version {to_version}: {str(e)}")
        to_contents = f"Unable to read to-version at {to_version}.\n"

    try:
        from_contents = watch.get_history_snapshot(timestamp=from_version)
    except Exception as e:
        logger.error(f"Unable to read watch history from-version for version {from_version}: {str(e)}")
        from_contents = f"Unable to read from-version {from_version}.\n"

    note = ''
    if str(from_version) != str(dates[-2]) or str(to_version) != str(dates[-1]):
        note = 'Note: You are not viewing the latest changes.'

    return DiffVersions(
        dates=dates,
        from_version=str(from_version),
        to_version=str(to_version),
        from_contents=from_contents,
        to_contents=to_contents,
        viewing_latest=str(to_version) == str(dates[-1]),
        note=note,
    )
