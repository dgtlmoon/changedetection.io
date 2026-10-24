#!/usr/bin/env python3
"""Live integration tests for the FlareSolverr overlay (needs a real daemon).

Skipped unless FLARESOLVERR_URL points at a running FlareSolverr, e.g.
    FLARESOLVERR_URL=http://127.0.0.1:8191/v1 pytest changedetectionio/tests/test_flaresolverr_integration.py

Targets mirror FlareSolverr's own suite (src/tests.py in the FlareSolverr repo):
* https://www.google.com — no challenge; proves pool+daemon wiring.
* https://httpbin.org/post — POST echo; proves the postData path.
* https://nowsecure.nl/ — FlareSolverr's reference Cloudflare target;
  proves the actual bypass (cf_clearance cookie + marker in response).

NOT covered here (needs a browser): cookie injection into Playwright/
Puppeteer/Selenium and the live Browser Steps UI — exercised manually.
"""

import asyncio
import os

import pytest

from changedetectionio.flaresolverr_pool import (
    FlarePool,
    get_flaresolverr_solution_for_watch,
    is_flaresolverr_enabled,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("FLARESOLVERR_URL"),
    reason="FLARESOLVERR_URL not set — needs a live FlareSolverr daemon",
)

GOOGLE_URL = "https://www.google.com"
HTTPBIN_POST_URL = "https://httpbin.org/post"
CLOUDFLARE_URL = "https://nowsecure.nl/"


def _pool(**kwargs):
    kwargs.setdefault("flaresolverr_url", os.environ["FLARESOLVERR_URL"])
    return FlarePool(**kwargs)


def _find_cookie(cookies, name):
    for c in cookies or []:
        if c.get("name") == name:
            return c
    return None


def test_daemon_reachable_and_enabled():
    assert is_flaresolverr_enabled() is True


def test_solve_no_challenge():
    solution = _pool().solve(GOOGLE_URL)
    assert solution["status"] == 200
    assert "Google" in (solution["response"] or "")
    assert solution["userAgent"] and "Chrome" in solution["userAgent"]


def test_solve_post_data():
    solution = _pool().solve(HTTPBIN_POST_URL, method="POST",
                             post_data="param1=value1&param2=value2")
    assert solution["status"] == 200
    assert '"param1": "value1"' in (solution["response"] or "")


def test_solve_cloudflare_challenge_and_session_reuse():
    # NOTE: assert on the cf_clearance cookie (the actual bypass proof),
    # not page markup — nowsecure.nl redesigned since FlareSolverr's own
    # suite pinned "<title>nowSecure</title>" (now "<title>nowsecure.nl</title>").
    pool = _pool()
    first = pool.solve(CLOUDFLARE_URL)
    assert first["status"] == 200
    assert "nowsecure" in (first["response"] or "").lower()
    cf_cookie = _find_cookie(first["cookies"], "cf_clearance")
    assert cf_cookie is not None, "Cloudflare cookie not found"
    assert len(cf_cookie["value"]) > 30
    second = pool.solve(CLOUDFLARE_URL)
    assert second["session_id"] == first["session_id"]


def test_solution_for_watch_end_to_end():
    from types import SimpleNamespace

    class FakeWatch(dict):
        @property
        def link(self):
            return self.get("link")

    datastore = SimpleNamespace(
        data={"settings": {"application": {"flaresolverr_enabled": True}, "requests": {}}})
    watch = FakeWatch({"link": CLOUDFLARE_URL, "method": "GET", "flaresolverr": "enabled"})
    solution = asyncio.run(get_flaresolverr_solution_for_watch(watch, datastore))
    assert solution["status"] == 200
    assert _find_cookie(solution["cookies"], "cf_clearance") is not None
