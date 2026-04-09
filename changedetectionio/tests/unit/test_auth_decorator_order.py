"""
Static analysis test: verify @login_optionally_required is always applied
AFTER (inner to) @blueprint.route(), not before it.

In Flask, @route() must be the outermost decorator because it registers
whatever function it receives. If @login_optionally_required is placed
above @route(), the raw unprotected function gets registered and auth is
silently bypassed (GHSA-jmrh-xmgh-x9j4).

Correct order (route outermost, auth inner):
    @blueprint.route('/path')
    @login_optionally_required
    def view(): ...

Wrong order (auth never called):
    @login_optionally_required   ← registered by route, then discarded
    @blueprint.route('/path')
    def view(): ...
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


def _is_auth_decorator(node: ast.expr) -> bool:
    """Return True if the decorator is @login_optionally_required."""
    return isinstance(node, ast.Name) and node.id == "login_optionally_required"


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
            auth_indices = [i for i, d in enumerate(decorators) if _is_auth_decorator(d)]
            route_indices = [i for i, d in enumerate(decorators) if _is_route_decorator(d)]

            # Bad order: auth decorator appears at a lower index (higher up) than a route decorator
            for auth_idx in auth_indices:
                for route_idx in route_indices:
                    if auth_idx < route_idx:
                        rel = path.relative_to(REPO_ROOT)
                        violations.append(
                            f"{rel}:{node.lineno} — `{node.name}`: "
                            f"@login_optionally_required (line {decorators[auth_idx].lineno}) "
                            f"is above @route (line {decorators[route_idx].lineno}); "
                            f"auth wrapper will never be called"
                        )

    return violations


def test_auth_decorator_order():
    violations = collect_violations()
    if violations:
        msg = (
            "\n\nFound routes where @login_optionally_required is placed ABOVE @blueprint.route().\n"
            "This silently disables authentication — @route() registers the raw function\n"
            "and the auth wrapper is never called.\n\n"
            "Fix: move @blueprint.route() to be the outermost (topmost) decorator.\n\n"
            + "\n".join(f"  • {v}" for v in violations)
        )
        pytest.fail(msg)
