"""
Static analysis test: verify @blueprint.route() is always the outermost
decorator on a view, so nothing sits above it.

In Flask, @route() must be outermost because it registers whatever function
it receives and then returns that function unchanged. Any decorator placed
above @route() is applied only to the module-level name, never to the view
the blueprint actually dispatches to — so it is silently dead code. When the
dead decorator is an auth wrapper, the route is left unprotected
(GHSA-jmrh-xmgh-x9j4).

Correct order (route outermost, auth inner):
    @blueprint.route('/path')
    @login_optionally_required
    def view(): ...

Wrong order (auth never called):
    @login_optionally_required   ← discarded; route registered the raw fn
    @blueprint.route('/path')
    def view(): ...

This check is deliberately name-agnostic. An earlier version matched only
the literal name `login_optionally_required`, which missed four routes using
plain flask_login `login_required` (GHSA-q85w-c766-h5g8) — an allowlist of
decorator names only ever catches the names someone remembered to add. We
now flag *any* non-route decorator above @route, which also covers attribute
forms (@flask_login.login_required), aliased imports, and non-auth
decorators that are equally dead up there.

Stacked @route decorators are a legitimate Flask idiom and are exempt.
"""

import ast
import pathlib
import pytest

REPO_ROOT = pathlib.Path(__file__).parents[3]  # …/changedetection.io/
SOURCE_ROOT = REPO_ROOT / "changedetectionio"


def _is_route_decorator(node: ast.expr) -> bool:
    """Return True if the decorator looks like @something.route(...)."""
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "route"
    )


def collect_violations() -> list[str]:
    violations = []

    for path in SOURCE_ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            decorators = node.decorator_list
            route_indices = [i for i, d in enumerate(decorators) if _is_route_decorator(d)]
            if not route_indices:
                continue

            # Everything above the last @route is discarded by the registration.
            # Other @route decorators up there are fine — stacking routes is normal.
            last_route = max(route_indices)
            for i, decorator in enumerate(decorators):
                if i < last_route and not _is_route_decorator(decorator):
                    rel = path.relative_to(REPO_ROOT)
                    violations.append(
                        f"{rel}:{node.lineno} — `{node.name}`: "
                        f"@{ast.unparse(decorator)} (line {decorator.lineno}) is above @route "
                        f"(line {decorators[last_route].lineno}); it will never be applied "
                        f"to the registered view"
                    )

    return violations


def test_auth_decorator_order():
    violations = collect_violations()
    if violations:
        msg = (
            "\n\nFound decorators placed ABOVE @blueprint.route().\n"
            "@route() registers the raw function and returns it unchanged, so anything\n"
            "above it is never applied to the view Flask dispatches to. If the decorator\n"
            "is an auth wrapper, the route is left completely unauthenticated.\n\n"
            "Fix: move @blueprint.route() to be the outermost (topmost) decorator.\n\n"
            + "\n".join(f"  • {v}" for v in violations)
        )
        pytest.fail(msg)
